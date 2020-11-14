import time
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn import model_selection
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.manifold import TSNE
from sklearn.linear_model import LogisticRegression

import stellargraph as sg
from stellargraph.mapper import (
    CorruptedGenerator,
    HinSAGENodeGenerator,
)
from stellargraph.layer import GCN, DeepGraphInfomax, GraphSAGE, GAT, APPNP, HinSAGE, Dense

import tensorflow as tf
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping
from tensorflow.keras import Model, optimizers, losses, metrics

def deepGraphInfomax(v_sets, e_sets, core_targets, ext_targets, v_sample, e_sample):
  print("DeepGraphInfomax Starting")
  
  batch_size = 300
  epochs = 50
  dropout = 0.5
  patience = 15
  verbose = 1
  num_samples = [8, 4]
  hinsage_layer_sizes = [32, 32]

  # Check if num_samples and layer_size are compatible
  assert len(hinsage_layer_sizes) == len(num_samples)

  # Initialize stellargraph object
  G = sg.StellarDiGraph(v_sets, e_sets)

  '''
  HinSAGENodeGenerator(G, batch_size, num_samples, head_node_type=None, schema=None, seed=None, name=None)

  G = graph
  batch_size = size of batch to return
  num_samples = the number of samples per layer (hop) to take
  head_node_type = the node type that will be given to the generator using the flow method. 
                  The model will expect this type.
                  If not given, it defaults to a single node type.
  '''

  def create_embeddings(node_type):

    generator = HinSAGENodeGenerator(
      G, 
      batch_size, 
      num_samples,
      head_node_type=node_type
    )

    # HinSAGE layers
    hinsage = HinSAGE(
      layer_sizes=hinsage_layer_sizes,
      activations=['relu', 'softmax'],
      generator=generator, 
      bias=True,
      normalize="l2",
      dropout=dropout
    )

    def run_deep_graph_infomax(base_model, generator, epochs, node_type):
      corrupted_generator = CorruptedGenerator(generator)
      gen = corrupted_generator.flow(G.nodes(node_type=node_type))
      infomax = DeepGraphInfomax(base_model, corrupted_generator)

      x_in, x_out = infomax.in_out_tensors()

      print("Starting Training")
      ttrain = time.time()
      # Train
      model = Model(inputs=x_in, outputs=x_out)
      model.compile(loss=tf.nn.sigmoid_cross_entropy_with_logits, optimizer=Adam(lr=1e-3))
      es = EarlyStopping(monitor="loss", min_delta=0, patience=patience)
      
      history = model.fit(gen, epochs=epochs, verbose=verbose, callbacks=[es])
      sg.utils.plot_history(history)
      
      ttrain1 = time.time()
      print(f"Training complete in {(ttrain1-ttrain):.2f} s ({(ttrain1-ttrain)/60:.2f} min)")

      x_emb_in, x_emb_out = base_model.in_out_tensors()
      # for full batch models, squeeze out the batch dim (which is 1)
      if generator.num_batch_dims() == 2:
          x_emb_out = tf.squeeze(x_emb_out, axis=0)

      return x_emb_in, x_emb_out

    # Run Deep Graph Infomax
    x_emb_in, x_emb_out = run_deep_graph_infomax(
      hinsage, generator, epochs=epochs, node_type=node_type)
    
    emb_model = Model(inputs=x_emb_in, outputs=x_emb_out)
    all_embeddings = emb_model.predict(
      generator.flow(G.nodes(node_type=node_type))
    )

    # TSNE visualization of embeddings
    ttsne = time.time()
    print("Creating TSNE")
    embeddings_2d = pd.DataFrame(TSNE(n_components=2).fit_transform(all_embeddings), index=G.nodes(node_type=node_type))

    # draw the points
    node_ids = G.nodes(node_type=node_type).tolist()
    ext_targets = v_sample.loc[[int(node_id) for node_id in node_ids]].ExtendedCaseGraphID 

    label_map = {l: i*10 for i, l in enumerate(np.unique(ext_targets), start=10) if pd.notna(l)}
    node_colours = [label_map[target] if pd.notna(target) else 0 for target in ext_targets]
    
    ttsne1 = time.time()
    print(f"TSNE completed in {(ttsne1-ttsne):.2f} s ({(ttsne1-ttsne)/60:.2f} min)")

    alpha = 0.7
    fig, ax = plt.subplots(figsize=(15, 15))
    ax.scatter(
        embeddings_2d[0],
        embeddings_2d[1],
        c=node_colours,
        cmap="jet",
        alpha=alpha,
    )
    ax.set(aspect="equal")
    plt.title(f'TSNE visualization of HinSAGE "{node_type}" embeddings with Deep Graph Infomax')
    plt.show()

    return all_embeddings



  def fake_embs():
    return [[2, 32, 4, 42, 12, 421, 42], [214, 21, 214, 24, 21, 42, 2]]
  
  # Repeat algorithm for every node type
  # (each node type requires a training phase)
  full_graph_embeddings = [None] * len(v_sets)
  i = 0
  for node_type in v_sets:
    full_graph_embeddings[i] = fake_embs()
    i += 1

  return 1