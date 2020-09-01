# coding: utf-8
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import print_function

import argparse
import logging
import os
import sys
import mxnet as mx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memegle_cnocr.consts import EMB_MODEL_TYPES, SEQ_MODEL_TYPES, MODEL_VERSION
from memegle_cnocr.utils import data_dir, set_logger
from memegle_cnocr.hyperparams.cn_hyperparams import CnHyperparams
from memegle_cnocr.data_utils.data_iter import GrayImageIter
from memegle_cnocr.data_utils.aug import FgBgFlipAug
from memegle_cnocr.symbols.crnn import gen_network
from memegle_cnocr.fit.ctc_metrics import CtcMetrics
from memegle_cnocr.fit.fit import fit


logger = set_logger(log_level=logging.INFO)


def parse_args():
    # Parse command line arguments
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--emb_model_type",
        help="which embedding model to use",
        choices=EMB_MODEL_TYPES,
        type=str,
        default='conv-lite',
    )
    parser.add_argument(
        "--seq_model_type",
        help='which sequence model to use',
        default='fc',
        type=str,
        choices=SEQ_MODEL_TYPES,
    )
    parser.add_argument(
        "--train_file",
        help="Path to train txt file",
        type=str,
        default='data/sample-data-lst/train.txt',
    )
    parser.add_argument(
        "--test_file",
        help="Path to test txt file",
        type=str,
        default='data/sample-data-lst/test.txt',
    )
    parser.add_argument(
        "--use_train_image_aug",
        action='store_true',
        help="Whether to use image augmentation for training",
    )
    parser.add_argument(
        "--gpu",
        help="Number of GPUs for training [Default 0, means using cpu]",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--optimizer",
        help="optimizer for training [Default: Adam]",
        type=str,
        default='Adam',
    )
    parser.add_argument(
        '--batch_size',
        type=int,
        default=128,
        help='batch size for each device [Default: 128]',
    )
    parser.add_argument(
        '--epoch', type=int, default=20, help='train epochs [Default: 20]'
    )
    parser.add_argument(
        '--load_epoch',
        type=int,
        help='load the model on an epoch using the model-load-prefix '
             '[Default: no trained model will be loaded]',
    )
    parser.add_argument('--lr', type=float, default=0.001, help='learning rate')
    parser.add_argument(
        '--dropout', type=float, default=0.5, help='dropout ratio [Default: 0.5]'
    )
    parser.add_argument(
        '--wd', type=float, default=0.0, help='weight decay factor [Default: 0.0]'
    )
    parser.add_argument(
        '--clip_gradient',
        type=float,
        default=None,
        help='value for clip gradient [Default: None, means no gradient will be clip]',
    )
    parser.add_argument(
        "--out_model_dir",
        help='output model directory',
        default=os.path.join(data_dir(), MODEL_VERSION),
    )
    return parser.parse_args()


def train_cnocr(args):
    head = '%(asctime)-15s %(message)s'
    logging.basicConfig(level=logging.DEBUG, format=head)
    args.model_name = args.emb_model_type + '-' + args.seq_model_type
    out_dir = os.path.join(args.out_model_dir, args.model_name)
    logger.info('save models to dir: %s' % out_dir)
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    args.prefix = os.path.join(
        out_dir, 'cnocr-v{}-{}'.format(MODEL_VERSION, args.model_name)
    )

    hp = CnHyperparams()
    hp = _update_hp(hp, args)

    network, hp = gen_network(args.model_name, hp)
    metrics = CtcMetrics(hp.seq_length)

    data_train, data_val = _gen_iters(
        hp, args.train_file, args.test_file, args.use_train_image_aug
    )
    data_names = ['data']
    fit(
        network=network,
        data_train=data_train,
        data_val=data_val,
        metrics=metrics,
        args=args,
        hp=hp,
        data_names=data_names,
    )


def _update_hp(hp, args):
    hp.seq_model_type = args.seq_model_type
    hp._num_epoch = args.epoch
    hp.optimizer = args.optimizer
    hp._batch_size = args.batch_size
    hp._learning_rate = args.lr
    hp._drop_out = args.dropout
    hp.wd = args.wd
    hp.clip_gradient = args.clip_gradient
    return hp


def _gen_iters(hp, train_fp_prefix, val_fp_prefix, use_train_image_aug):
    height, width = hp.img_height, hp.img_width
    augs = None
    if use_train_image_aug:
        augs = mx.image.CreateAugmenter(
            data_shape=(3, height, width),
            resize=0,
            rand_crop=False,
            rand_resize=False,
            rand_mirror=False,
            mean=None,
            std=None,
            brightness=0.001,
            contrast=0.001,
            saturation=0.001,
            hue=0.05,
            pca_noise=0.1,
            inter_method=2,
        )
        augs.append(FgBgFlipAug(p=0.2))
    train_iter = GrayImageIter(
        batch_size=hp.batch_size,
        data_shape=(3, height, width),
        label_width=hp.num_label,
        dtype='int32',
        shuffle=True,
        path_imgrec=str(train_fp_prefix) + ".rec",
        path_imgidx=str(train_fp_prefix) + ".idx",
        aug_list=augs,
    )

    val_iter = GrayImageIter(
        batch_size=hp.batch_size,
        data_shape=(3, height, width),
        label_width=hp.num_label,
        dtype='int32',
        path_imgrec=str(val_fp_prefix) + ".rec",
        path_imgidx=str(val_fp_prefix) + ".idx",
    )

    return train_iter, val_iter


if __name__ == '__main__':
    args = parse_args()
    train_cnocr(args)
