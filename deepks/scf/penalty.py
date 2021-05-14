import time
import numpy as np
from pyscf.dft import numint, gen_grid
from pyscf.scf.hf import dip_moment
from pyscf.lib import logger
from deepks.utils import check_list


def select_penalty(name):
    name = name.lower()
    if name == "density":
        return DensityPenalty
    if name == "coulomb":
        return CoulombPenalty
    if name == "dipole":
        return DipolePenalty
    raise ValueError(f"unknown penalty type: {name}")


class PenaltyMixin(object):
    """Mixin class to add penalty potential in Fock matrix"""

    def __init__(self, penalties=None):
        self.penalties = check_list(penalties)
        for pnt in self.penalties:
            pnt.init_hook(self)

    def get_fock(self, h1e=None, s1e=None, vhf=None, dm=None, cycle=-1, 
                 diis=None, diis_start_cycle=None, 
                 level_shift_factor=None, damp_factor=None):
        """modified get_fock method to apply penalty terms onto vhf"""
        if dm is None:
            dm = self.make_rdm1()
        if h1e is None: 
            h1e = self.get_hcore()
        if vhf is None: 
            vhf = self.get_veff(dm=dm)
        vp = sum(pnt.fock_hook(self, dm=dm, h1e=h1e, vhf=vhf, cycle=cycle) 
                    for pnt in self.penalties)
        vhf = vhf + vp
        return super().get_fock(h1e=h1e, s1e=s1e, vhf=vhf, dm=dm, cycle=cycle, 
                        diis=diis, diis_start_cycle=diis_start_cycle, 
                        level_shift_factor=level_shift_factor, damp_factor=damp_factor)


class AbstructPenalty(object):
    """
    Abstruct class for penalty term in scf hamiltonian.
    To implement a penalty one needs to implement 
    fock_hook and (optional) init_hook methods.
    """
    required_labels = [] # the label would be load and pass to __init__

    def init_hook(self, mf, **envs):
        """
        Method to be called when initialize the scf object.
        Used to initialize the penalty with molecule info.
        """
        pass

    def fock_hook(self, mf, dm=None, h1e=None, vhf=None, cycle=-1, **envs):
        """
        Method to be called before get_fock is called.
        The returned matrix would be added to the vhf matrix
        """
        raise NotImplementedError("fock_hook method is not implemented")


class DummyPenalty(AbstructPenalty):
    def fock_hook(self, mf, dm=None, h1e=None, vhf=None, cycle=-1, **envs):
        return 0


class DensityPenalty(AbstructPenalty):
    r"""
    penalty on the difference w.r.t target density
    E_p = \lambda / 2 * \int dx (\rho(x) - \rho_target(x))^2
    V_p = \lambda * \int dx <ao_i|x> (\rho(x) - \rho_target(x)) <x|ao_j> 
    The target density should be given as density matrix in ao basis
    """
    required_labels = ["dm"]

    def __init__(self, target_dm, strength=1, random=False, start_cycle=0):
        if isinstance(target_dm, str):
            target_dm = np.load(target_dm)
        self.dm_t = target_dm
        self.init_strength = strength
        self.strength = strength * np.random.rand() if random else strength
        self.start_cycle = start_cycle
        # below are values to be initialized later in init_hook
        self.grids = None
        self.ao_value = None

    def init_hook(self, mf, **envs):
        if hasattr(mf, "grid"):
            self.grids = mf.grids
        else:
            self.grids = gen_grid.Grids(mf.mol)

    def fock_hook(self, mf, dm=None, h1e=None, vhf=None, cycle=-1, **envs):
        # cycle > 0 means it is doing scf iteration
        if 0 <= cycle < self.start_cycle:
            return 0
        if self.grids.coords is None:
            self.grids.build()
        if self.ao_value is None:
            self.ao_value = numint.eval_ao(mf.mol, self.grids.coords, deriv=0)
        tic = (time.clock(), time.time())
        rho_diff = numint.eval_rho(mf.mol, self.ao_value, dm - self.dm_t)
        v_p = numint.eval_mat(mf.mol, self.ao_value, self.grids.weights, rho_diff, rho_diff)
        # cycle < 0 means it is just checking, we only print here
        if cycle < 0 and mf.verbose >=4:
            diff_norm = np.sum(np.abs(rho_diff)*self.grids.weights)
            logger.info(mf, f"  Density Penalty: |diff| = {diff_norm}")
            logger.timer(mf, "dens_pnt", *tic)
        return self.strength * v_p


class CoulombPenalty(AbstructPenalty):
    r"""
    penalty given by the coulomb energy of density difference

    """
    required_labels = ["dm"]

    def __init__(self, target_dm, strength=1, random=False, start_cycle=0):
        if isinstance(target_dm, str):
            target_dm = np.load(target_dm)
        self.dm_t = target_dm
        self.init_strength = strength
        self.strength = strength * np.random.rand() if random else strength
        self.start_cycle = start_cycle

    def fock_hook(self, mf, dm=None, h1e=None, vhf=None, cycle=-1, **envs):
        # cycle > 0 means it is doing scf iteration
        if 0 <= cycle < self.start_cycle:
            return 0
        tic = (time.clock(), time.time())
        ddm = dm - self.dm_t
        v_p = mf.get_j(dm=ddm)
        # cycle < 0 means it is just checking, we only print here
        if cycle < 0 and mf.verbose >=4:
            diff_norm = np.sum(ddm * v_p)
            logger.info(mf, f"  Coulomb Penalty: |diff| = {diff_norm}")
            logger.timer(mf, "coul_pnt", *tic)
        return self.strength * v_p

class DipolePenalty(AbstructPenalty):
    r"""
    penalty on the difference w.r.t target dipole
    D = \lambda / 2 * |\vec p - \vec p_target|^2
    v_xc = (\vec p - \vec p_label) \cdot \vec r
    The target dipole should be given as 1D vector [3]
    """
    required_labels = ["dipole"]

    def __init__(self, target_p, strength=1, random=False, start_cycle=0):
        self.p_t = target_p
        self.init_strength = strength
        self.strength = strength * np.random.rand() if random else strength
        self.start_cycle = start_cycle
        # below are values to be initialized later in init_hook
        self.grids = None
        self.ao_value = None

    def init_hook(self, mf, **envs):
        if hasattr(mf, "grid"):
            self.grids = mf.grids
        else:
            self.grids = gen_grid.Grids(mf.mol)

    def fock_hook(self, mf, dm=None, h1e=None, vhf=None, cycle=-1, **envs):
        # cycle > 0 means it is doing scf iteration
        if 0 <= cycle < self.start_cycle:
            return 0
        if self.grids.coords is None:
            self.grids.build()
        if self.ao_value is None:
            self.ao_value = numint.eval_ao(mf.mol, self.grids.coords, deriv=0)
        tic = (time.clock(), time.time())
        p = dip_moment(mf.mol, dm)
        dp = p - self.p_t
        kernel = np.dot(self.grids.coords, dp)
        v_p = numint.eval_mat(mf.mol, self.ao_value, self.grids.weights, None, kernel) # it doesn't really need a rho!
        # cycle < 0 means it is just checking, we only print here
        if cycle < 0 and mf.verbose >=4:
            diff_norm = np.sum(dp * dp)
            logger.info(mf, f"  Dipole Penalty: |diff| = {diff_norm}")
            logger.timer(mf, "dip_pnt", *tic)
        return self.strength * v_p
