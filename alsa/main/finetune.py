# -*- coding: utf-8 -*-

import random
from comet_ml import Experiment, api
import torch
import numpy as np
from alsa.config import comet_ml_key, username
from alsa.main.args import get_args, get_net_cls
from alsa.adaptation.label_shift import label_shift
from alsa.datasets.datasets import get_datasets
from alsa.nets.common import evaluate, train


def experiment():
    """Run finetuning label shift exp"""
    args = get_args(None)
    name = "Finetune {}:{}:{} {}:{} {}:{}:{}:{} {}{}v{}".format(
        args.dataset,
        args.dataset_cap,
        args.warmstart_ratio,
        args.shift_strategy,
        args.dirichlet_alpha,
        args.shift_correction,
        args.rlls_reg,
        args.rlls_lambda,
        args.lr,
        "IW " if args.train_iw else "NOIW ",
        "ITIW " if args.iterative_iw else "NOITIW ",
        args.version,
    )

    # Initialize comet.ml
    if args.log:
        comet_api = api.API(api_key=comet_ml_key)
        exps = comet_api.get_experiments(
            username,
            project_name="active-label-shift-adaptation",
            pattern=name)
        for exp in exps:
            if exp.get_name() == name:
                raise ValueError("EXP EXISTS!")
        logger = Experiment(
            comet_ml_key,
            project_name="active-label-shift-adaptation")
        logger.set_name(name)
        logger.log_parameters(vars(args))

    # Seed the experiment
    seed = args.seed
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    print("Running seed ", seed)
    torch.cuda.set_device(args.device)
    assert torch.cuda.is_available()

    # Shuffle dataset
    dataset = get_datasets(args)
    dataset.label_ptrs(np.arange(dataset.online_len()))

    # Train h0
    net_cls = get_net_cls(args)
    network = net_cls(args.num_cls).to(args.device)

    def log_fn(epoch):
        network.eval()
        accuracy = evaluate(network, dataset.iterate(
            args.infer_batch_size, False, split="test"), args.device, args, label_weights=dataset.label_weights)
        print(accuracy)
        logger.log_metrics(accuracy, prefix="initial", step=epoch)
    train(
        network,
        dataset=dataset,
        epochs=args.initial_epochs,
        args=args,
        log_fn=log_fn)

    # Get source shift corrections
    lsmse = label_shift(network, dataset, args)

    def log_fn_shifted(epoch):
        network.eval()
        if args.iterative_iw:
            label_shift(network, dataset, args)
        accuracy = evaluate(network, dataset.iterate(
            args.infer_batch_size, False, split="test"), args.device, args, label_weights=dataset.label_weights)
        print(accuracy)
        logger.log_metrics(accuracy, prefix="shifted", step=epoch)
    train(
        network,
        dataset=dataset,
        epochs=args.initial_epochs,
        args=args,
        log_fn=log_fn_shifted)

    if args.iterative_iw:
        lsmse = label_shift(network, dataset, args)
    logger.log_metrics({"IW MSE": lsmse}, prefix="initial")


if __name__ == "__main__":
    experiment()
