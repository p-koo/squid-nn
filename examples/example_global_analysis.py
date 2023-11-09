"""
Demonstration of how to perform SQUID global analysis with example Kipoi model (BPNet)

Due to BPNet requiring incompatible libraries with MAVE-NN, the current script is separated
into two parts (with switches 'STEP 1' and 'STEP 2'). STEP 1 requires an activated BPNet environment.
Once outputs are saved to file, deactivate the environment and activate the MAVE-NN environment.
Finally, turn off the STEP 1 switch below (i.e., 'if 0:') and rerun this script.

For using Kipoi models, the following packages must be installed:
    >>> pip install kipoi --upgrade
    >>> pip install kipoiseq --upgrade

For instruction on installing the BPNet environment, see:
https://github.com/evanseitz/squid-manuscript/blob/main/examples/README_environments.md
"""

import os, sys
sys.dont_write_bytecode = True


# =============================================================================
# Computational settings
# =============================================================================
gpu = False
save = True # required for BPNet with MAVE-NN analysis


# =============================================================================
# Main pipeline
# =============================================================================
py_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(py_dir)
save_dir = os.path.join(py_dir, 'outputs_global_analysis')
if not os.path.exists(save_dir):
    os.makedirs(save_dir)


task_idx = 'Nanog' # bpnet task index ('Oct4', 'Sox2', 'Klf4' or 'Nanog')
alphabet = ['A','C','G','T']
seq_length = 1000 # full sequence length of bpnet inputs

# define global pattern (i.e., conserved sequence of interest)
pattern = 'AGCCATCAA' # e.g., Nanog binding site

start_pos = int(seq_length//2) # position of inserted pattern in background DNA
seq = 'N'*int(seq_length//2) + pattern + ('N'*int(seq_length//2))[:-len(pattern)] # pad pattern with background sequence
mut_window = [start_pos, start_pos+len(pattern)] # interval in sequence to mutagenize locally


if 1: # STEP 1 (BPNet)
    import kipoi
    import numpy as np
    sys.path.append(os.path.join(parent_dir, 'squid'))
    import utils, predictor, mutagenizer, mave # import squid modules manually



    # convert to one-hot
    x = utils.seq2oh(seq, alphabet)

    # instantiate kipoi model for bpnet
    model = kipoi.get_model('BPNet-OSKN')

    # define how to go from kipoi prediction to scalar
    kipoi_predictor = predictor.BPNetPredictor(model.predict_on_batch, task_idx=task_idx, batch_size=512)

    # set up mutagenizer class for in silico MAVE
    mut_generator = mutagenizer.RandomMutagenesis(mut_rate=0.1, uniform=False)

    # generate in silico MAVE
    seq_length = len(x)
    mut_window = [0, seq_length] # interval in sequence to mutagenize
    num_sim = 10000 # number of sequence to simulate
    mave = mave.InSilicoMAVE(mut_generator, mut_predictor=kipoi_predictor, seq_length=seq_length, mut_window=mut_window,
                             context_agnostic=True) # required for global analysis 
    x_mut, y_mut = mave.generate(x, num_sim=num_sim)

    # save in silico MAVE dataset for STEP 2
    print('Saving in silico MAVE dataset...')
    np.save(os.path.join(save_dir, 'x_mut.npy'), x_mut)
    np.save(os.path.join(save_dir, 'y_mut.npy'), y_mut)
    

else: # STEP 2 (MAVE-NN)
    import mavenn
    import squid
    import matplotlib.pyplot as plt

    # choose surrogate model type
    gpmap = 'additive'

    # load in in silico MAVE dataset from STEP 1
    x_mut = np.load(os.path.join(save_dir, 'x_mut.npy'))
    y_mut = np.load(os.path.join(save_dir, 'y_mut.npy'))

    # MAVE-NN model with GE nonlinearity
    surrogate_model = squid.surrogate_zoo.SurrogateMAVENN(x_mut.shape, num_tasks=y_mut.shape[1],
                                                    gpmap=gpmap, regression_type='GE',
                                                    linearity='nonlinear', noise='SkewedT',
                                                    noise_order=2, reg_strength=0.1,
                                                    alphabet=alphabet, deduplicate=True,
                                                    gpu=gpu)

    # train surrogate model
    surrogate, mave_df = surrogate_model.train(x_mut, y_mut, learning_rate=5e-4, epochs=500, batch_size=100,
                                            early_stopping=True, patience=25, restore_best_weights=True,
                                            save_dir=None, verbose=1)

    # retrieve model parameters
    params = surrogate_model.get_params(gauge='empirical')

    # generate sequence logo
    logo = surrogate_model.get_logo(mut_window=mut_window, full_length=seq_length)

    logo_df = squid.utils.arr2pd(logo, alphabet)
    print(logo_df)
    logo_df.to_csv(os.path.join(save_dir, 'logo.csv'))

    # plot additive logo in wildtype gauge
    fig = squid.impress.plot_additive_logo(logo, center=True, view_window=mut_window, alphabet=alphabet, fig_size=[20,2.5], save_dir=save_dir)