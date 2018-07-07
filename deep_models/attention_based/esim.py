#!/Users/sunnymarkliu/softwares/miniconda3/bin/python
# _*_ coding: utf-8 _*_

"""
@author: SunnyMarkLiu
@time  : 2018/6/29 下午3:16
"""
import sys

sys.path.append("../")
import warnings

warnings.filterwarnings('ignore')
from keras.models import Model
from keras.initializers import Constant
from keras.utils import plot_model
from base_model import BaseModel
from utils.keras_layers import *


class Esim(BaseModel):

    def build_model(self, data):
        shared_embedding_layer = Embedding(data['nb_words'],
                                    self.cfg.embedding_dim,
                                    weights=[data['word_embedding_matrix']],
                                    input_length=self.cfg.max_sequence_length,
                                    trainable=self.cfg.embed_trainable)
        shared_embed_dropout_layer = SpatialDropout1D(self.cfg.esim_cfg['embed_dropout'])

        seq_1_input = Input(shape=(self.cfg.max_sequence_length,), dtype='int16')
        seq_2_input = Input(shape=(self.cfg.max_sequence_length,), dtype='int16')

        # Embedding
        embed_seq_1 = shared_embed_dropout_layer(shared_embedding_layer(seq_1_input))
        embed_seq_2 = shared_embed_dropout_layer(shared_embedding_layer(seq_2_input))

        # Encode
        shared_encode_layer = Bidirectional(GRU(units=self.cfg.esim_cfg['rnn_units'],
                                                dropout=0.2,
                                                recurrent_dropout=0.2,
                                                return_sequences=True), merge_mode='concat')
        q1_encoded = shared_encode_layer(embed_seq_1)
        q2_encoded = shared_encode_layer(embed_seq_2)

        # Attention
        q1_aligned, q2_aligned = soft_attention_alignment(q1_encoded, q2_encoded)

        # Compose
        q1_combined = Concatenate()([q1_encoded, q1_aligned, diff_features(q1_encoded, q1_aligned)])
        q2_combined = Concatenate()([q2_encoded, q2_aligned, diff_features(q2_encoded, q2_aligned)])

        compose_layer = Bidirectional(GRU(units=self.cfg.esim_cfg['rnn_units'],
                                          dropout=0.2,
                                          recurrent_dropout=0.2,
                                          return_sequences=True))
        reduction_layer = TimeDistributed(Dense(units=self.cfg.esim_cfg['rnn_units'],
                                                kernel_initializer='he_normal',
                                                activation='relu'))
        q1_compare = Dropout(self.cfg.esim_cfg['dense_dropout'])(
            reduction_layer(compose_layer(q1_combined))
        )
        q2_compare = Dropout(self.cfg.esim_cfg['dense_dropout'])(
            reduction_layer(compose_layer(q2_combined))
        )

        # Aggregate
        q1_rep = apply_multiple(q1_compare, [GlobalAvgPool1D(), GlobalMaxPool1D()])
        q2_rep = apply_multiple(q2_compare, [GlobalAvgPool1D(), GlobalMaxPool1D()])

        # Classifier
        merged = Concatenate()([q1_rep, q2_rep])
        dense = BatchNormalization()(merged)
        print('MLP input:', dense)

        for dense_unit in self.cfg.esim_cfg['dense_units']:
            dense = Dense(
                units=dense_unit,
                activation=self.cfg.esim_cfg['activation'],
                bias_initializer=Constant(value=0.01)
            )(dense)
            dense = BatchNormalization()(dense)
            dense = Dropout(self.cfg.esim_cfg['dense_dropout'])(dense)

        preds = Dense(1, activation='sigmoid')(dense)
        model = Model(inputs=[seq_1_input, seq_2_input], outputs=preds)
        model.compile(loss='binary_crossentropy', optimizer=self.cfg.esim_cfg['optimizer'],
                      metrics=['binary_accuracy'])
        # model.summary()
        plot_model(model, to_file='../assets/Esim.png', show_shapes=True, show_layer_names=True)

        return model
