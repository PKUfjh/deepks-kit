import os,time,sys
import numpy as np
import torch


class Reader(object):
    def __init__(self, data_path, batch_size, 
                 e_name="l_e_delta", d_name="dm_eig", 
                 conv_filter=True, conv_name="conv", **kwargs):
        # copy from config
        self.data_path = data_path
        self.batch_size = batch_size
        self.e_name = e_name
        self.d_name = d_name if isinstance(d_name, (list, tuple)) else [d_name]
        self.c_filter = conv_filter
        self.c_name = conv_name
        self.load_meta()
        self.prepare()

    def load_meta(self):
        try:
            sys_meta = np.loadtxt(os.path.join(self.data_path,'system.raw'), dtype = int).reshape([-1])
            self.natm = sys_meta[0]
            self.nproj = sys_meta[-1]
        except:
            print('#', self.data_path, f"no system.raw, infer meta from data", file=sys.stderr)
            sys_shape = np.load(os.path.join(self.data_path, f'{self.d_name[0]}.npy')).shape
            assert len(sys_shape) == 3, \
                f"{self.d_name[0]} has to be an order-3 array with shape [nframes, natom, nproj]"
            self.natm = sys_shape[1]
            self.nproj = sys_shape[2]
    
    def prepare(self):
        self.index_count_all = 0
        data_ec = np.load(os.path.join(self.data_path,f'{self.e_name}.npy')).reshape([-1, 1])
        raw_nframes = data_ec.shape[0]
        data_dm = np.concatenate(
            [np.load(os.path.join(self.data_path,f'{dn}.npy'))\
               .reshape([raw_nframes, self.natm, self.nproj])
            for dn in self.d_name], 
            axis=-1)
        if self.c_filter:
            conv = np.load(os.path.join(self.data_path,f'{self.c_name}.npy')).reshape(raw_nframes)
        else:
            conv = np.ones(raw_nframes, dtype=bool)
        self.data_ec = data_ec[conv]
        self.data_dm = data_dm[conv]
        self.nframes = conv.sum()
        self.ndesc = self.data_dm.shape[-1]
        # print(np.shape(self.inputs_train))
        if self.nframes < self.batch_size:
            self.batch_size = self.nframes
            print('#', self.data_path, f"reset batch size to {self.batch_size}", file=sys.stderr)
    
    def sample_train(self):
        if self.nframes == self.batch_size == 1:
            return self.sample_all()
        self.index_count_all += self.batch_size
        if self.index_count_all > self.nframes:
            # shuffle the data
            self.index_count_all = self.batch_size
            ind = np.random.choice(self.nframes, self.nframes, replace=False)
            self.data_ec = self.data_ec[ind]
            self.data_dm = self.data_dm[ind]
        ind = np.arange(self.index_count_all - self.batch_size, self.index_count_all)
        return \
            torch.from_numpy(self.data_ec[ind]), \
            torch.from_numpy(self.data_dm[ind])

    def sample_all(self) :
        return \
            torch.from_numpy(self.data_ec), \
            torch.from_numpy(self.data_dm)

    def get_train_size(self) :
        return self.nframes

    def get_batch_size(self) :
        return self.batch_size

    def get_nframes(self) :
        return self.nframes


class ForceReader(object):
    def __init__(self, data_path, batch_size, 
                 e_name="l_e_delta", d_name="dm_eig", 
                 f_name="l_f_delta", gv_name="grad_vx", 
                 conv_filter=True, conv_name="conv", **kwargs):
        self.data_path = data_path
        self.batch_size = batch_size
        self.e_name = e_name
        self.f_name = f_name
        self.d_name = d_name
        self.gv_name = gv_name
        self.c_filter = conv_filter
        self.c_name = conv_name
        # load data
        self.load_meta()
        self.prepare()
        # initialize sample index queue
        self.idx_queue = []

    def load_meta(self):
        try:
            sys_meta = np.loadtxt(os.path.join(self.data_path,'system.raw'), dtype = int).reshape([-1])
            self.natm = sys_meta[0]
            self.nproj = sys_meta[-1]
        except:
            print('#', self.data_path, f"no system.raw, infer meta from data", file=sys.stderr)
            sys_shape = np.load(os.path.join(self.data_path, f'{self.d_name}.npy')).shape
            assert len(sys_shape) == 3, \
                f"{self.d_name[0]} has to be an order-3 array with shape [nframes, natom, nproj]"
            self.natm = sys_shape[1]
            self.nproj = sys_shape[2]
        self.ndesc = self.nproj

    def prepare(self):
        # load energy and check nframes
        data_ec = np.load(os.path.join(self.data_path, f'{self.e_name}.npy')).reshape([-1, 1])
        raw_nframes = data_ec.shape[0]
        data_dm = np.load(os.path.join(self.data_path, f'{self.d_name}.npy'))\
                    .reshape([raw_nframes, self.natm, self.ndesc])
        if self.c_filter:
            conv = np.load(os.path.join(self.data_path,f'{self.c_name}.npy')).reshape(raw_nframes)
        else:
            conv = np.ones(raw_nframes, dtype=bool)
        self.data_ec = data_ec[conv]
        self.data_dm = data_dm[conv]
        self.nframes = conv.sum()
        if self.nframes < self.batch_size:
            self.batch_size = self.nframes
            print('#', self.data_path, f"reset batch size to {self.batch_size}", file=sys.stderr)
        # load data in torch
        self.t_ec = torch.tensor(self.data_ec)
        self.t_eig = torch.tensor(self.data_dm)
        self.t_fc = torch.tensor(
            np.load(os.path.join(self.data_path, f'{self.f_name}.npy'))\
              .reshape(raw_nframes, self.natm, 3)[conv]
        )
        self.t_gvx = torch.tensor(
            np.load(os.path.join(self.data_path, f'{self.gv_name}.npy'))\
              .reshape(raw_nframes, self.natm, 3, self.natm, self.ndesc)[conv]
        )
        # pin memory
        if torch.cuda.is_available():
            self.t_ec = self.t_ec.pin_memory()
            self.t_fc = self.t_fc.pin_memory()
            self.t_eig = self.t_eig.pin_memory()
            self.t_gvx = self.t_gvx.pin_memory()

    def sample_train(self):
        if self.batch_size == self.nframes == 1:
            return self.sample_all()
        if len(self.idx_queue) < self.batch_size:
            self.idx_queue = np.random.choice(self.nframes, self.nframes, replace=False)
        sample_idx = self.idx_queue[:self.batch_size]
        self.idx_queue = self.idx_queue[self.batch_size:]
        return \
            self.t_ec[sample_idx], \
            self.t_eig[sample_idx], \
            self.t_fc[sample_idx], \
            self.t_gvx[sample_idx]

    def sample_all(self):
        return \
            self.t_ec, \
            self.t_eig, \
            self.t_fc, \
            self.t_gvx

    def get_train_size(self):
        return self.nframes

    def get_batch_size(self):
        return self.batch_size

    def get_nframes(self):
        return self.nframes

class OrbitalReader(object):
    def __init__(self, data_path, batch_size, 
                 e_name="l_e_delta", d_name="dm_eig", 
                 f_name="l_f_delta", gv_name="grad_vx", 
                 o_name="l_o_delta",
                 op_name="orbital_precalc",
                 conv_filter=True, conv_name="conv", **kwargs):
        self.data_path = data_path
        self.batch_size = batch_size
        self.e_name = e_name
        self.f_name = f_name
        self.d_name = d_name
        self.gv_name = gv_name
        self.o_name = o_name
        self.op_name = op_name
        self.c_filter = conv_filter
        self.c_name = conv_name
        # load data
        self.load_meta()
        self.prepare()
        # initialize sample index queue
        self.idx_queue = []

    def load_meta(self):
        try:
            sys_meta = np.loadtxt(os.path.join(self.data_path,'system.raw'), dtype = int).reshape([-1])
            self.natm = sys_meta[0]
            self.nproj = sys_meta[-1]
        except:
            print('#', self.data_path, f"no system.raw, infer meta from data", file=sys.stderr)
            sys_shape = np.load(os.path.join(self.data_path, f'{self.d_name}.npy')).shape
            assert len(sys_shape) == 3, \
                f"{self.d_name[0]} has to be an order-3 array with shape [nframes, natom, nproj]"
            self.natm = sys_shape[1]
            self.nproj = sys_shape[2]
        self.ndesc = self.nproj

    def prepare(self):
        # load energy and check nframes
        data_ec = np.load(os.path.join(self.data_path, f'{self.e_name}.npy')).reshape([-1, 1])
        raw_nframes = data_ec.shape[0]
        data_dm = np.load(os.path.join(self.data_path, f'{self.d_name}.npy'))\
                    .reshape([raw_nframes, self.natm, self.ndesc])
        if self.c_filter:
            conv = np.load(os.path.join(self.data_path,f'{self.c_name}.npy')).reshape(raw_nframes)
        else:
            conv = np.ones(raw_nframes, dtype=bool)
        self.data_ec = data_ec[conv]
        self.data_dm = data_dm[conv]
        self.nframes = conv.sum()
        if self.nframes < self.batch_size:
            self.batch_size = self.nframes
            print('#', self.data_path, f"reset batch size to {self.batch_size}", file=sys.stderr)
        # load data in torch
        self.t_ec = torch.tensor(self.data_ec)
        self.t_eig = torch.tensor(self.data_dm)
        self.t_fc = torch.tensor(
            np.load(os.path.join(self.data_path, f'{self.f_name}.npy'))\
              .reshape(raw_nframes, self.natm, 3)[conv]
        )
        self.t_gvx = torch.tensor(
            np.load(os.path.join(self.data_path, f'{self.gv_name}.npy'))\
              .reshape(raw_nframes, self.natm, 3, self.natm, self.ndesc)[conv]
        )
        self.t_oc = torch.tensor(
            np.load(os.path.join(self.data_path, f'{self.o_name}.npy'))\
              .reshape(raw_nframes, -1)[conv]
        )
        self.t_op = torch.tensor(
            np.load(os.path.join(self.data_path, f'{self.op_name}.npy'))\
              .reshape(raw_nframes, -1, self.natm, self.ndesc)[conv]
        )
        # pin memory
        if torch.cuda.is_available():
            self.t_ec = self.t_ec.pin_memory()
            self.t_fc = self.t_fc.pin_memory()
            self.t_eig = self.t_eig.pin_memory()
            self.t_gvx = self.t_gvx.pin_memory()
            self.t_oc = self.t_oc.pin_memory()
            self.t_op = self.t_op.pin_memory()

    def sample_train(self):
        if self.batch_size == self.nframes == 1:
            return self.sample_all()
        if len(self.idx_queue) < self.batch_size:
            self.idx_queue = np.random.choice(self.nframes, self.nframes, replace=False)
        sample_idx = self.idx_queue[:self.batch_size]
        self.idx_queue = self.idx_queue[self.batch_size:]
        return \
            self.t_ec[sample_idx], \
            self.t_eig[sample_idx], \
            self.t_fc[sample_idx], \
            self.t_gvx[sample_idx], \
            self.t_oc[sample_idx], \
            self.t_op[sample_idx]

    def sample_all(self):
        return \
            self.t_ec, \
            self.t_eig, \
            self.t_fc, \
            self.t_gvx, \
            self.t_oc, \
            self.t_op

    def get_train_size(self):
        return self.nframes

    def get_batch_size(self):
        return self.batch_size

    def get_nframes(self):
        return self.nframes

class GroupReader(object) :
    def __init__ (self, path_list, batch_size=1, group_batch=1, with_force=False, with_orbital=False, **kwargs) :
        if isinstance(path_list, str):
            path_list = [path_list]
        self.path_list = path_list
        self.batch_size = batch_size
        # init system readers
        Reader_class = OrbitalReader if with_orbital else ForceReader if with_force else Reader
        self.readers = []
        self.nframes = []
        for ipath in self.path_list :
            ireader = Reader_class(ipath, batch_size, **kwargs)
            if ireader.get_nframes() == 0:
                print('# ignore empty dataset:', ipath, file=sys.stderr)
                continue
            self.readers.append(ireader)
            self.nframes.append(ireader.get_nframes())
        self.nsystems = len(self.readers)
        # probability of each system
        self.ndesc = self.readers[0].ndesc
        self.sys_prob = [float(ii) for ii in self.nframes] / np.sum(self.nframes)
        
        self.group_batch = max(group_batch, 1)
        if self.group_batch > 1:
            self.group_dict = {}
            # self.group_index = {}
            for idx, r in enumerate(self.readers):
                if r.natm in self.group_dict:
                    self.group_dict[r.natm].append(r)
                    # self.group_index[r.natm].append(idx)
                else:
                    self.group_dict[r.natm] = [r]
                    # self.group_index[r.natm] = [idx]
            self.group_prob = {n: sum(r.nframes for r in r_list) / sum(self.nframes)
                                for n, r_list in self.group_dict.items()}
            self.batch_prob_raw = {n: [r.nframes / r.batch_size for r in r_list] 
                                for n, r_list in self.group_dict.items()}
            self.batch_prob = {n: p / np.sum(p) for n, p in self.batch_prob_raw.items()}

        self._sample_used = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._sample_used > self.get_train_size():
            self._sample_used = 0
            raise StopIteration
        sample = self.sample_train() if self.group_batch == 1 else self.sample_train_group()
        self._sample_used += sample[0].shape[0]
        return sample

    def sample_idx(self) :
        return np.random.choice(np.arange(self.nsystems), p=self.sys_prob)
        
    def sample_train(self, idx=None) :
        if idx is None:
            idx = self.sample_idx()
        return \
            self.readers[idx].sample_train()

    def sample_train_group(self):
        cnatm = np.random.choice(list(self.group_prob.keys()), p=list(self.group_prob.values()))
        cgrp = self.group_dict[cnatm]
        csys = np.random.choice(cgrp, self.group_batch, p=self.batch_prob[cnatm])
        all_sample = list(zip(*[s.sample_train() for s in csys]))
        return [torch.cat(d, dim=0) for d in all_sample]

    def sample_all(self, idx=None) :
        if idx is None:
            idx = self.sample_idx()
        return \
            self.readers[idx].sample_all()
    
    def sample_all_batch(self, idx=None):
        if idx is not None:
            all_data = self.sample_all(idx)
            size = self.batch_size * self.group_batch
            yield from zip(*[torch.split(all_data[i], size, dim=0) for i in range(len(all_data))])
        else:
            for i in range(self.nsystems):
                yield from self.sample_all_batch(i)

    def get_train_size(self) :
        return np.sum(self.nframes)

    def get_batch_size(self) :
        return self.batch_size

    def compute_data_stat(self, symm_sections=None):
        all_dm = np.concatenate([r.data_dm.reshape(-1,r.ndesc) for r in self.readers])
        if symm_sections is None:
            all_mean, all_std = all_dm.mean(0), all_dm.std(0)
        else:
            assert sum(symm_sections) == all_dm.shape[-1]
            dm_shells = np.split(all_dm, np.cumsum(symm_sections)[:-1], axis=-1)
            mean_shells = [d.mean().repeat(s) for d, s in zip(dm_shells, symm_sections)]
            std_shells = [d.std().repeat(s) for d, s in zip(dm_shells, symm_sections)]
            all_mean = np.concatenate(mean_shells, axis=-1)
            all_std = np.concatenate(std_shells, axis=-1)
        return all_mean, all_std

    def compute_prefitting(self, shift=None, scale=None, ridge_alpha=1e-8, symm_sections=None):
        if shift is None or scale is None:
            all_mean, all_std = self.compute_data_stat(symm_sections=symm_sections)
            if shift is None:
                shift = all_mean
            if scale is None:
                scale = all_std
        all_sdm = np.concatenate([((r.data_dm - shift) / scale).sum(1) for r in self.readers])
        all_natm = np.concatenate([[float(r.data_dm.shape[1])]*r.data_dm.shape[0] for r in self.readers])
        if symm_sections is not None: # in this case ridge alpha cannot be 0
            assert sum(symm_sections) == all_sdm.shape[-1]
            sdm_shells = np.split(all_sdm, np.cumsum(symm_sections)[:-1], axis=-1)
            all_sdm = np.stack([d.sum(-1) for d in sdm_shells], axis=-1)
        # build feature matrix
        X = np.concatenate([all_sdm, all_natm.reshape(-1,1)], -1)
        y = np.concatenate([r.data_ec for r in self.readers])
        I = np.identity(X.shape[1])
        I[-1,-1] = 0 # do not punish the bias term
        # solve ridge reg
        coef = np.linalg.solve(X.T @ X + ridge_alpha * I, X.T @ y).reshape(-1)
        weight, bias = coef[:-1], coef[-1]
        if symm_sections is not None:
            weight = np.concatenate([w.repeat(s) for w, s in zip(weight, symm_sections)], axis=-1)
        return weight, bias