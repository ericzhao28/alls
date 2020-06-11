"""Wrap the NABirds dataset in torchvision style."""

import warnings
import os
import numpy as np
import pandas as pd
from torchvision.datasets import VisionDataset
from torchvision.datasets.folder import default_loader
from torchvision.datasets.utils import check_integrity, extract_archive
from alsa.main.args import get_args


class NABirds(VisionDataset):
    """`NABirds <https://dl.allaboutbirds.org/nabirds>`_ Dataset.

        Args:
            root (string): Root directory of the dataset.
            train (bool, optional): If True, creates dataset from training set, otherwise
               creates from test set.
            transform (callable, optional): A function/transform that  takes in an PIL image
               and returns a transformed version. E.g, ``transforms.RandomCrop``
            target_transform (callable, optional): A function/transform that takes in the
               target and transforms it.
            download (bool, optional): If true, downloads the dataset from the internet and
               puts it in root directory. If dataset is already downloaded, it is not
               downloaded again.
    """
    base_folder = 'nabirds/images'
    filename = 'nabirds.tar.gz'
    md5 = 'df21a9e4db349a14e2b08adfd45873bd'

    def __init__(self, root, train=True, transform=None, target_transform=None, download=None):
        super(NABirds, self).__init__(
            root, transform=transform, target_transform=target_transform)
        if download is True:
            msg = ("The dataset is no longer publicly accessible. You need to "
                   "download the archives externally and place them in the root "
                   "directory.")
            raise RuntimeError(msg)
        msg = ("The use of the download flag is deprecated, since the dataset "
               "is no longer publicly accessible.")
        warnings.warn(msg, RuntimeWarning)

        dataset_path = os.path.join(root, "nabirds")
        print(dataset_path)
        if not os.path.isdir(dataset_path):
            if not check_integrity(os.path.join(root, self.filename), self.md5):
                raise RuntimeError('Dataset not found or corrupted.')
            extract_archive(os.path.join(root, self.filename))
        self.loader = default_loader
        self.train = train

        image_paths = pd.read_csv(os.path.join(dataset_path, 'images.txt'),
                                  sep=' ', names=['img_id', 'filepath'])
        image_class_labels = pd.read_csv(os.path.join(dataset_path, 'image_class_labels.txt'),
                                         sep=' ', names=['img_id', 'target'])
        image_bounding_boxes = pd.read_csv(os.path.join(dataset_path, 'bounding_boxes.txt'),
                                           sep=' ', names=['img_id', 'x', 'y', 'w', 'h'])
        # Since the raw labels are non-continuous, map them to new ones
        self.label_map = get_continuous_class_map(image_class_labels['target'])
        train_test_split = pd.read_csv(os.path.join(dataset_path, 'train_test_split.txt'),
                                       sep=' ', names=['img_id', 'is_training_img'])
        data = image_paths.merge(image_class_labels, on='img_id')
        data = data.merge(image_bounding_boxes, on='img_id')
        self.data = data.merge(train_test_split, on='img_id')
        # Load in the train / test split
        if self.train:
            self.data = self.data[self.data.is_training_img == 1]
        else:
            self.data = self.data[self.data.is_training_img == 0]

        # Load in the class data
        self.class_names = load_class_names(dataset_path)
        self.class_hierarchy = load_hierarchy(dataset_path)
        self.targets = None

    def change_class_map(self, args):
        changed = True
        child_map = {k: [] for k in self.class_hierarchy.keys()}
        child_map['0'] = []

        for k, v in self.class_hierarchy.items():
            child_map[v].append(k)

        children = child_map['0']

        if args.nabirdstype == "grand":
            grandchildren = []
            for child in children:
                grandchildren += child_map[child]

            changed = True
            parent_map = self.class_hierarchy.copy()
            parent_map['0'] = '0'
            while changed:
                changed = False
                for k, v in parent_map.items():
                    if v in grandchildren or v == '0':
                        continue
                    changed = True
                    parent_map[k] = parent_map[v]
        elif args.nabirdstype == "child":
            changed = True
            parent_map = self.class_hierarchy.copy()
            parent_map['0'] = '0'
            while changed:
                changed = False
                for k, v in parent_map.items():
                    if v in children or v == '0':
                        continue
                    changed = True
                    parent_map[k] = parent_map[v]

        for k, v in list(parent_map.items()):
            if v == '0':
                parent_map.pop(k)

        self.label_map = {int(k): int(v) for k, v in parent_map.items()}
        uniq_vals = sorted(list(set(list(self.label_map.values()))))

        for k, v in self.label_map.items():
            self.label_map[k] = uniq_vals.index(v)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        sample = self.data.iloc[idx]
        path = os.path.join(self.root, self.base_folder, sample.filepath)
        target = self.label_map[sample.target]
        img = self.loader(path)

        img = img.crop((sample.x, sample.y, sample.x +
                        sample.w, sample.y + sample.h))

        if self.transform is not None:
            img = self.transform(img)
        if self.target_transform is not None:
            target = self.target_transform(target)
        return img, target

    def get_target(self, idx):
        sample = self.data.iloc[idx]
        target = self.label_map[int(sample.target)]
        return target


def get_continuous_class_map(class_labels):
    """Renumerate labels"""
    label_set = set(class_labels)
    return {k: i for i, k in enumerate(label_set)}


def load_class_names(dataset_path=''):
    """Load class names."""
    names = {}

    with open(os.path.join(dataset_path, 'classes.txt')) as f:
        for line in f:
            pieces = line.strip().split()
            class_id = pieces[0]
            names[class_id] = ' '.join(pieces[1:])

    return names


def load_hierarchy(dataset_path=''):
    """Load label hierarchy."""
    parents = {}

    with open(os.path.join(dataset_path, 'hierarchy.txt')) as f:
        for line in f:
            pieces = line.strip().split()
            child_id, parent_id = pieces
            parents[child_id] = parent_id

    return parents


if __name__ == '__main__':
    train_dataset = NABirds('/content/data',
                            train=True, download=False)
    args = get_args("--nabirdstype child")
    print(train_dataset.change_class_map(args))
    print(train_dataset.get_target(0))
    print(len(np.unique(list(train_dataset.label_map.values()))))
