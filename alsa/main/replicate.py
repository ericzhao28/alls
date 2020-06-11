# -*- coding: utf-8 -*-

import random
import os
import csv
from comet_ml import Experiment, api
import torch
import numpy as np
from alsa.config import comet_ml_key, LONG_MILESTONES, NABIRDS_MILESTONES, username
from alsa.adaptation.label_shift import label_shift
from alsa.adaptation.utils import measure_composition
from alsa.datasets.datasets import get_datasets
from alsa.main.args import get_net_cls, get_args
from alsa.nets.alt_common import train as sep_train
from alsa.nets.common import evaluate, train
from alsa.sampling import general_sampling


def save_to_csv(name, d, args, logger):
    keys = list(d.keys())
    num_batches = len(d[keys[0]])
    d["Batch #"] = list(range(num_batches))
    d["Name"] = num_batches * [name]

    keys = list(d.keys())
    fname = 'data/%s.csv' % name
    with open(fname, 'w') as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        for i in range(num_batches):
            w.writerow({k: v[i] for k, v in d.items()})

    logger.log_asset(fname, overwrite=True, step=d["Batch #"][-1])


def experiment(args, logger, name, seed=None):
    """Run LS experiment"""

    # Seed the experiment
    if seed is None:
        seed = args.seed
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    print("Running seed ", seed)
    torch.cuda.set_device(args.device)
    assert torch.cuda.is_available()
    if args.reweight:
        assert args.iterative_iw

    assert args.shift_correction in ["rlls", "bbse", "cheat", "none"]

    # Shuffle dataset
    dataset = get_datasets(args)

    # Load
    net_cls = get_net_cls(args)
    network = net_cls(args.num_cls).to(args.device)

    # Train h0
    # milestones = NABIRDS_MILESTONES if args.dataset == "nabirds" else LONG_MILESTONES
    milestones = LONG_MILESTONES

    # Check for h0
    if args.dataset == "nabirds":
        fname = "./data/%s_%s_%s_%s_%s.h5" % (args.seed, args.dataset_cap,
                                         args.dataset, args.nabirdstype, args.version)
    else:
        fname = "./data/%s_%s_%s_%s_%s_%s.h5" % (args.seed, args.dataset_cap,
                                            args.dataset, args.shift_strategy, args.warmstart_ratio, args.version)
    if os.path.exists(fname):
        checkpoint = torch.load(fname, map_location=torch.device(args.device))
        network.load_state_dict(checkpoint)
        network = network.to(args.device)
    else:
        train(
            network,
            dataset=dataset,
            epochs=args.initial_epochs,
            args=args,
            milestones=milestones)
        if args.domainsep:
            sep_train(
                network,
                dataset=dataset,
                epochs=args.initial_epochs,
                args=args)
        torch.save(network.state_dict(), fname)
    label_shift(network, dataset, args)

    # Initialize sampling strategy
    iterator = general_sampling(
        network,
        net_cls,
        dataset,
        args)

    # Initialize results
    _, initial_labeled_shift, initial_uniform_labeled_shift = measure_composition(
        dataset)
    initial_accuracy = evaluate(network, dataset.iterate(
        args.infer_batch_size, False, split="test"), args.device, args, label_weights=dataset.label_weights)

    num_labeled = [0]
    labeled_shifts = [initial_labeled_shift]
    uniform_labeled_shifts = [initial_uniform_labeled_shift]
    accuracies = {k: [v] for k, v in initial_accuracy.items()}

    metrics = {
        "Number of labels": num_labeled,
        "Source shift": labeled_shifts,
        "Uniform source shift": uniform_labeled_shifts,
    }
    metrics.update(accuracies)
    for k, v in metrics.items():
        logger.log_metric(k, v[-1], step=metrics["Number of labels"][-1])
    print(metrics)
    save_to_csv(name, metrics, args, logger)

    # Begin sampling
    for network in iterator:
        # Evaluate current network
        network.eval()
        accuracy = evaluate(network, dataset.iterate(
            args.infer_batch_size, False, split="test"), args.device, args, label_weights=dataset.label_weights)
        for k, v in accuracy.items():
            accuracies[k].append(v)
        num_labeled.append(dataset.online_labeled_len())

        new_optimal_weights, labeled_shift, uniform_labeled_shift = measure_composition(
            dataset)
        labeled_shifts.append(labeled_shift)
        uniform_labeled_shifts.append(uniform_labeled_shift)
        print("Optimal weights for new source", new_optimal_weights)

        # Record metrics
        metrics = {
            "Number of labels": num_labeled,
            "Source shift": labeled_shifts,
            "Uniform source shift": uniform_labeled_shifts,
        }
        metrics.update(accuracies)
        for k, v in metrics.items():
            logger.log_metric(k, v[-1], step=metrics["Number of labels"][-1])
        print(metrics)
        save_to_csv(name, metrics, args, logger)

    logger.log_metric("Done", True)
    return metrics


def seeded_exp(cmd):
    """Run seeded exps"""
    args = get_args(cmd)
    args.name = "{}zz{}zz{}zz{}zz{}zz{}zz{}zz{}zz{}zz{}zz{}zz{}zz{}".format(
        args.sampling_strategy,
        args.diversify,
        args.shift_correction,
        "IW" if args.train_iw else "NOIW",
        "ITIW" if args.iterative_iw else "NOITIW",
        "reweight" if args.reweight else "",
        "norllsinfer" if not args.rlls_infer else "",
        "onlyrllsinfer" if args.only_rlls_infer else "",
        args.version,
        args.shift_strategy,
        args.dirichlet_alpha,
        args.dataset,
        args.warmstart_ratio,
    )
    name = args.name + " " + str(args.seed)

    # Initialize comet.ml
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

    # Run experiments
    this_metrics = experiment(args, logger, name, seed=args.seed)
    print(this_metrics)


if __name__ == "__main__":
    seeded_exp(None)