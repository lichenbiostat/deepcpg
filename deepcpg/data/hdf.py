import re

import h5py as h5
import numpy as np

from ..utils import filter_regex


def _ls(item, recursive=False, groups=False, level=0):
    keys = []
    if isinstance(item, h5.Group):
        if groups and level > 0:
            keys.append(item.name)
        if level == 0 or recursive:
            for key in list(item.keys()):
                keys.extend(_ls(item[key], recursive, groups, level + 1))
    elif not groups:
        keys.append(item.name)
    return keys


def ls(filename, group='/', recursive=False, groups=False,
       regex=None, nb_keys=None):
    if not group.startswith('/'):
        group = '/%s' % group
    h5_file = h5.File(filename, 'r')
    keys = _ls(h5_file[group], recursive, groups)
    for i, key in enumerate(keys):
        keys[i] = re.sub('^%s/' % group, '', key)
    h5_file.close()
    if regex:
        keys = filter_regex(keys, regex)
    if nb_keys:
        keys = keys[:nb_keys]
    return keys


def write_data(data, filename):
    is_root = isinstance(filename, str)
    group = h5.File(filename, 'w') if is_root else filename
    for key, value in data.items():
        if isinstance(value, dict):
            key_group = group.create_group(key)
            write_data(value, key_group)
        else:
            group[key] = value
    if is_root:
        group.close()


def hnames_to_names(hnames):
    names = []
    for key, value in hnames.items():
        if isinstance(value, dict):
            for name in hnames_to_names(value):
                names.append('%s/%s' % (key, name))
        elif isinstance(value, list):
            for name in value:
                names.append('%s/%s' % (key, name))
        elif isinstance(value, str):
            names.append('%s/%s' % (key, value))
        else:
            names.append(key)
    return names


def reader(data_files, names, batch_size=128, nb_sample=None, shuffle=False,
           loop=False):
    if not isinstance(data_files, list):
        data_files = [data_files]
    # Copy, since it might be changed by shuffling
    data_files = list(data_files)
    if isinstance(names, dict):
        names = hnames_to_names(names)

    if nb_sample:
        # Select the first k files s.t. the total sample size is at least
        # nb_sample. Only these files will be shuffled.
        _data_files = []
        nb_seen = 0
        for data_file in data_files:
            h5_file = h5.File(data_file, 'r')
            nb_seen += len(h5_file[names[0]])
            h5_file.close()
            _data_files.append(data_file)
            if nb_seen >= nb_sample:
                break
        data_files = _data_files
    else:
        nb_sample = np.inf

    file_idx = 0
    nb_seen = 0
    while True:
        if shuffle and file_idx == 0:
            np.random.shuffle(data_files)

        h5_file = h5.File(data_files[file_idx], 'r')
        data_file = dict()
        for name in names:
            data_file[name] = h5_file[name]
        nb_sample_file = len(list(data_file.values())[0])

        if shuffle:
            # Shuffle data within the entire file, which requires reading
            # the entire file into memory
            idx = np.arange(nb_sample_file)
            np.random.shuffle(idx)
            for name, value in data_file.items():
                data_file[name] = value[:len(idx)][idx]

        nb_batch = int(np.ceil(nb_sample_file / batch_size))
        for batch in range(nb_batch):
            batch_start = batch * batch_size
            nb_read = min(nb_sample - nb_seen, batch_size)
            batch_end = min(nb_sample_file, batch_start + nb_read)
            _batch_size = batch_end - batch_start
            if _batch_size == 0:
                break
            nb_seen += _batch_size

            data_batch = dict()
            for name in names:
                data_batch[name] = data_file[name][batch_start:batch_end]
            yield data_batch

            if nb_seen >= nb_sample:
                break

        h5_file.close()
        file_idx += 1
        assert nb_seen <= nb_sample
        if nb_sample == nb_seen:
            assert file_idx == len(data_files)
        if file_idx == len(data_files):
            if loop:
                file_idx = 0
                nb_seen = 0
            else:
                break


def _to_dict(data):
    if isinstance(data, np.ndarray):
        data = [data]
    return dict(zip(range(len(data)), data))


def read_from(reader, nb_sample=None):
    from .utils import stack_dict

    data = dict()
    nb_seen = 0
    is_dict = True

    for data_batch in reader:
        if not isinstance(data_batch, dict):
            data_batch = _to_dict(data_batch)
            is_dict = False
        for key, value in data_batch.items():
            values = data.setdefault(key, [])
            values.append(value)
        nb_seen += len(list(data_batch.values())[0])
        if nb_sample and nb_seen >= nb_sample:
            break

    data = stack_dict(data)
    if nb_sample:
        for key, value in data.items():
            data[key] = value[:nb_sample]

    if not is_dict:
        data = [data[i] for i in range(len(data))]

    return data


def read(data_files, names, nb_sample=None, batch_size=1024, *args, **kwargs):
    data_reader = reader(data_files, names, batch_size=batch_size,
                         nb_sample=nb_sample, loop=False, *args, **kwargs)
    return read_from(data_reader, nb_sample)
