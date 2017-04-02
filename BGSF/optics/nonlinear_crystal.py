# -*- coding: utf-8 -*-
"""
"""
from __future__ import (division, print_function)
import collections
import numpy as np

import declarative

from . import ports
from . import bases
from . import standard_attrs
from ..utilities.print import pprint

from ..system.matrix_injections import (
    FactorCouplingBase,
)


class ExpMatCoupling(FactorCouplingBase):
    """
    Generated by a dict-dict mapping ddlt[out][in] = list-tup-expr
    where list-tup-expr are a means of expressing addition and multiplication as lists and tups.

    lists represent series addition

    tups represent series multiplication, the first term is a raw number coefficient and any further are keys in the source
    vector
    """

    #must redefine since it was a property
    edges_req_pkset_dict = None
    def __init__(
        self,
        ddlt,
        in_map,
        out_map,
        N_ode = 1,
        order = 2,
    ):
        self.N_ode   = N_ode
        self.order   = order
        self.ddlt    = ddlt
        self.out_map = out_map
        self.in_map  = in_map

        #all edges are generated immediately. Currently assumes full density
        self.edges_NZ_pkset_dict = {}
        self.edges_pkpk_dict = {}
        self.edges_req_pkset_dict = {}
        def gen_edge_func(pk_in, pk_out):
            return lambda sV, sB: self.edge_func(pk_in, pk_out, sV, sB)
        for pk_out in self.out_map.values():
            if pk_out is None:
                continue
            for pk_in in self.in_map.values():
                self.edges_NZ_pkset_dict[(pk_in, pk_out)] = frozenset()
                self.edges_pkpk_dict[(pk_in, pk_out)] = gen_edge_func(pk_in, pk_out)
                self.edges_req_pkset_dict[(pk_in, pk_out)] = frozenset(self.in_map.values())

        #Currently, nonlinear doesn't need to make any sources. It may in the future as that may be a more stable way to converge
        self.sources_pk_dict = {}
        self.sources_NZ_pkset_dict = {}

        pks = set()
        def pks_grab(lt):
            if isinstance(lt, list):
                for sublt in lt:
                    pks_grab(sublt)
            elif isinstance(lt, tuple):
                for pk in lt[1:]:
                    pks.add(pk)
            else:
                raise RuntimeError("BOO")
            return
        for pk_out, din in self.ddlt.items():
            pks.add(pk_out)
            for pk_in, lt in din.items():
                pks.add(pk_in)
                pks_grab(lt)

        #print(ins_p, sol_vector)
        self.pks = list(pks)
        self.pks.sort()
        self.pks_inv = dict()
        for idx, pk in enumerate(self.pks):
            self.pks_inv[pk] = idx

        h = 1 / self.N_ode
        #remap the index keys into integer indexes for speed
        ddlt_accel = dict()
        def ddlt_remap(lt):
            if isinstance(lt, list):
                sublist = []
                for sublt in lt:
                    sublist.append(ddlt_remap(sublt))
                return sublist
            elif isinstance(lt, tuple):
                #get the gain
                newtup = [lt[0] * h]
                for pk in lt[1:]:
                    newtup.append(self.pks_inv[pk])
                return tuple(newtup)
            else:
                raise RuntimeError("BOO")
            return
        for pk_out, din in self.ddlt.items():
            for pk_in, lt in din.items():
                ddlt_accel[self.pks_inv[pk_out], self.pks_inv[pk_in]] = ddlt_remap(lt)
        self.ddlt_accel = ddlt_accel

        def ddlt_mult(lt, lt2):
            def ddlt_mult2(lt, lt2):
                if isinstance(lt2, list):
                    sublist = []
                    for sublt2 in lt2:
                        sublist = sublist + ddlt_mult2(lt, sublt2)
                    return sublist
                elif isinstance(lt2, tuple):
                    #multiply the gains and merge the indices
                    return [(lt2[0] * lt[0],) + lt[1:] + lt2[1:]]
                else:
                    raise RuntimeError("BOO")
            if isinstance(lt, list):
                sublist = []
                for sublt in lt:
                    sublist = sublist + ddlt_mult(sublt, lt2)
                return sublist
            elif isinstance(lt, tuple):
                return ddlt_mult2(lt, lt2)
            else:
                raise RuntimeError("BOO")
            return

        ddlt_accel_SE = dict()
        #put in the diagonals first
        for idx, pk in enumerate(self.pks):
            ddlt_accel_SE[idx, idx] = [(1,)]

        for pk_out, din in self.ddlt.items():
            pk_out_idx = self.pks_inv[pk_out]
            for pk_in, lt in din.items():
                pk_in_idx = self.pks_inv[pk_in]
                assert(pk_out_idx != pk_in_idx)
                for col_idx, pk in enumerate(self.pks):
                    #needs to multiply everything
                    lt_rm = ddlt_remap(lt)
                    lt_keep = ddlt_accel_SE.get((pk_out_idx, col_idx), [])
                    lt_mult = ddlt_accel_SE.get((pk_in_idx, col_idx), [])
                    ddlt_accel_SE[pk_out_idx, col_idx] = lt_keep + ddlt_mult(lt_mult, lt_rm)

        ddlt_accel_SE_use = dict()
        for (idx_out, idx_in), lt in ddlt_accel_SE.items():
            if idx_out == idx_in:
                if lt and lt[0] == (1,):
                    lt = lt[1:]
                else:
                    lt = lt + [(-1,)]
            if lt:
                ddlt_accel_SE_use[idx_out, idx_in] = lt
        #pprint(ddlt_accel_SE_use)

        self.ddlt_accel = ddlt_accel
        self.ddlt_accel = ddlt_accel_SE_use
        #pprint("PKS:")
        #pprint(pks)

    _prev_sol_vector = None

    def edge_func(self, pk_in, pk_out, sol_vector, sB):
        if sol_vector != self._prev_sol_vector:
            self._prev_sol_vector = sol_vector
            if self.order > 0:
                self.generate_solution(sol_vector)
            elif self.order == 0:
                self.generate_solution_RK(sol_vector)
            elif self.order < 0:
                self.generate_solution_SE(sol_vector)
        return self.solution.get((pk_in, pk_out), 0)

    def generate_solution(self, sol_vector):
        pks = self.pks
        pkv = np.empty(len(pks), dtype=object)
        for idx, pk in enumerate(pks):
            #print("PK_G: ", (ins_p, pk))
            pkv[idx] = sol_vector.get(self.in_map[pk], 0)
        pkO = pkv.copy()
        #print("PKV: ", pkv)
        #try:
        #    import tabulate
        #    tabular_data = [[str(label)] + [pk] for label, pk in zip(pks, pkv)]
        #    print("PKs:")
        #    print(tabulate.tabulate(tabular_data))
        #except ImportError:
        #    print("XXXX")

        def lt_val(lt):
            if isinstance(lt, list):
                val = 0
                for sublt in lt:
                    val = lt_val(sublt) + val
            elif isinstance(lt, tuple):
                val = lt[0]
                #print("LT0: ", val)
                for pk_idx in lt[1:]:
                    val = val * pkv[pk_idx]  # sol_vector.get(pk, 0)
            else:
                raise RuntimeError("BOO")
            return val

        eye = np.eye(len(pks), dtype = object)
        Mexp_tot = eye
        for idx_N in range(self.N_ode):
            m1 = np.zeros([len(pks), len(pks)], dtype = object)
            for (idx_out, idx_in), lt in self.ddlt_accel.items():
                    val = lt_val(lt)
                    m1[idx_out, idx_in] = val
            #print("M1: ", m1)
            Mexp = m1 + eye
            mmem = m1
            #try:
            #    import tabulate
            #    tabular_data = [[str(idx)] + list(td) for idx, (label, td) in enumerate(zip(pks, m1))]
            #    print("M1")
            #    print(m1.dtype)
            #    print(tabulate.tabulate(tabular_data))
            #except ImportError:
            #    print("XXXX")
            #try:
            #    import tabulate
            #    tabular_data = [[str(idx)] + list(str(x) for x in td) for idx, (label, td) in enumerate(zip(pks, Mexp))]
            #    print("Mexp", 1)
            #    print(Mexp.dtype)
            #    print(tabulate.tabulate(tabular_data))
            #except ImportError:
            #    print("XXXX")
            for idx in range(2, self.order+1):
                mmem = (1 / idx) * np.dot(m1, mmem)
                #try:
                #    import tabulate
                #    tabular_data = [[str(idx)] + list(td) for idx, (label, td) in enumerate(zip(pks, mmem))]
                #    print("mmem", idx)
                #    print(mmem.dtype)
                #    print(tabulate.tabulate(tabular_data))
                #except ImportError:
                #    print("XXXX")
                Mexp = Mexp + mmem
            #try:
            #    import tabulate
            #    tabular_data = [[str(idx)] + list(str(x) for x in td) for idx, (label, td) in enumerate(zip(pks, Mexp))]
            #    print("Mexp", idx)
            #    print(Mexp.dtype)
            #    print(tabulate.tabulate(tabular_data))
            #except ImportError:
            #    print("XXXX")
            #import scipy.linalg
            #Mexp2 = scipy.linalg.expm(m1.astype(complex))
            #try:
            #    import tabulate
            #    tabular_data = [[str(idx)] + list(str(x) for x in td) for idx, (label, td) in enumerate(zip(pks, Mexp2))]
            #    print("Mexp2", idx)
            #    print(Mexp2.dtype)
            #    print(tabulate.tabulate(tabular_data))
            #except ImportError:
            #    print("XXXX")
            ### IMPROVE POWER CONSERVATION
            #for idx in range(len(pks)):
            #    NORMsq = np.dot(Mexp[idx], Mexp[idx].conjugate())
            #    #print("pwr ", idx, " VAL: ", NORMsq)
            #    Mexp[idx] = Mexp[idx] / (NORMsq.real)**.5
            Mexp_tot = np.dot(Mexp, Mexp_tot)
            #print(Mexp.shape, pkv.shape)
            pkv = np.dot(Mexp, pkv.reshape(-1, 1)).reshape(-1)
            #try:
            #    import tabulate
            #    tabular_data = [[str(label)] + [str(pk), str(pkk)] for label, pk, pkk in zip(pks, pkv, pkX)]
            #    print("PKs2:")
            #    print(tabulate.tabulate(tabular_data))
            #except ImportError:
            #    print("XXXX")
            #print("pkv2:", type(pkv), pkv.shape)
            #print(pkv)

        #print(m1)
        #print(Mexp)
        #try:
        #    import tabulate
        #    tabular_data = [[str(label)] + [pk] for label, pk in zip(pks, pkv)]
        #    print("PKs2:")
        #    print(tabulate.tabulate(tabular_data))
        #except ImportError:
        #    print("XXXX")
        #try:
        #    import tabulate
        #    tabular_data = [[str(idx)] + list(str(x) for x in td) for idx, (label, td) in enumerate(zip(pks, Mexp_tot))]
        #    print("Mexp_tot", idx)
        #    print(Mexp.dtype)
        #    print(tabulate.tabulate(tabular_data))
        #except ImportError:
        #    print("XXXX")

        solution = dict()
        for idx_in in range(len(pks)):
            for idx_out in range(len(pks)):
                edge = Mexp_tot[idx_out, idx_in]
                if np.any(edge != 0):
                    #pk_in = pks[idx_in]
                    #pk_out = pks[idx_out]
                    ###TODO: add debug config reference for this print
                    #print(pk_in)
                    #print(pk_out)
                    #print(idx_in, idx_out, edge)
                    pkin = self.in_map[pks[idx_in]]
                    pkout = self.out_map[pks[idx_out]]
                    if pkout is None:
                        continue
                    solution[pkin, pkout] = edge

        #pprint(pks)

        self.solution = solution

    def generate_solution_RK(self, sol_vector):
        pks = self.pks
        pkv = np.empty(len(pks), dtype=object)
        for idx, pk in enumerate(pks):
            #print("PK_G: ", (ins_p, pk))
            pkv[idx] = sol_vector.get(self.in_map[pk], 0)

        def lt_val(lt, pkv):
            if isinstance(lt, list):
                val = 0
                for sublt in lt:
                    val = lt_val(sublt, pkv) + val
            elif isinstance(lt, tuple):
                val = lt[0]
                #print("LT0: ", val)
                for pk_idx in lt[1:]:
                    val = val * pkv[pk_idx]  # sol_vector.get(pk, 0)
            else:
                raise RuntimeError("BOO")
            return val

        eye = np.eye(len(pks), dtype = object)
        Mexp_tot = eye
        for idx_N in range(self.N_ode):
            mk1 = np.zeros([len(pks), len(pks)], dtype = object)
            #the current ddlt_accel already incorporates h, so we must reverse that for the Runge Kutta Solver
            h = 1 / self.N_ode
            for (idx_out, idx_in), lt in self.ddlt_accel.items():
                    val = lt_val(lt, pkv) / h
                    mk1[idx_out, idx_in] = val

            pkv_k1 = np.dot(mk1, pkv.reshape(-1, 1)).reshape(-1)
            mk2 = np.zeros([len(pks), len(pks)], dtype = object)
            for (idx_out, idx_in), lt in self.ddlt_accel.items():
                    val = lt_val(lt, pkv + h/2 * pkv_k1) / h
                    mk2[idx_out, idx_in] = val

            pkv_k2 = np.dot(mk2, pkv.reshape(-1, 1)).reshape(-1)
            mk3 = np.zeros([len(pks), len(pks)], dtype = object)
            for (idx_out, idx_in), lt in self.ddlt_accel.items():
                    val = lt_val(lt, pkv + h/2 * pkv_k2) / h
                    mk3[idx_out, idx_in] = val

            pkv_k3 = np.dot(mk3, pkv.reshape(-1, 1)).reshape(-1)
            mk4 = np.zeros([len(pks), len(pks)], dtype = object)
            for (idx_out, idx_in), lt in self.ddlt_accel.items():
                    val = lt_val(lt, pkv + h * pkv_k3) / h
                    mk4[idx_out, idx_in] = val

            #try:
            #    import tabulate
            #    tabular_data = [[str(idx)] + list(str(t) for t in td) for idx, (label, td) in enumerate(zip(pks, mk1))]
            #    print("MK1")
            #    print(tabulate.tabulate(tabular_data))
            #    tabular_data = [[str(idx)] + list(str(t) for t in td) for idx, (label, td) in enumerate(zip(pks, mk2))]
            #    print("MK2")
            #    print(tabulate.tabulate(tabular_data))
            #    tabular_data = [[str(idx)] + list(str(t) for t in td) for idx, (label, td) in enumerate(zip(pks, mk3))]
            #    print("MK3")
            #    print(tabulate.tabulate(tabular_data))
            #    tabular_data = [[str(idx)] + list(str(t) for t in td) for idx, (label, td) in enumerate(zip(pks, mk4))]
            #    print("MK4")
            #    print(tabulate.tabulate(tabular_data))
            #except ImportError:
            #    print("XXXX")

            Mexp = eye + h/6 * (mk1 + 2 * mk2 + 2 * mk3 + mk4)
            Mexp_tot = np.dot(Mexp, Mexp_tot)
            pkv = np.dot(Mexp, pkv.reshape(-1, 1)).reshape(-1)

        solution = dict()
        for idx_in in range(len(pks)):
            for idx_out in range(len(pks)):
                edge = Mexp_tot[idx_out, idx_in]
                if np.any(edge != 0):
                    #pk_in = pks[idx_in]
                    #pk_out = pks[idx_out]
                    ###TODO: add debug config reference for this print
                    #print(pk_in)
                    #print(pk_out)
                    #print(idx_in, idx_out, edge)
                    pkin = self.in_map[pks[idx_in]]
                    pkout = self.out_map[pks[idx_out]]
                    if pkout is None:
                        continue
                    solution[pkin, pkout] = edge

        #pprint(pks)

        self.solution = solution



class NonlinearCrystal(
    bases.OpticalCouplerBase,
    bases.SystemElementBase,
):
    """
    """
    @declarative.dproperty
    def N_ode(self, val = 10):
        """
        Number of iterations to use in the ODE solution
        """
        val = self.ooa_params.setdefault('N_ode', val)
        return val

    @declarative.dproperty
    def solution_order(self, val = 3):
        """
        Taylor expansion order used for the expM in the ODE solution
        """
        val = self.ooa_params.setdefault('solution_order', val)
        return val

    @declarative.dproperty
    def nlg(self, val):
        """
        This is in rtW/(W * mm)

        Should al
        """
        val = self.ooa_params.setdefault('nlg', val)
        return val

    #@declarative.dproperty
    #def length_mm(self, val = 10):
    #    """
    #    in [mm]
    #    """
    #    val = self.ooa_params.setdefault('length_mm', val)
    #    return val

    _length_default = '10mm'
    length = standard_attrs.generate_length()

    @declarative.dproperty
    def loss(self, val = 0):
        """
        in W/(W * mm)
        """
        #not yet implemented
        assert(val == 0)
        return val

    def __build__(self):
        super(NonlinearCrystal, self).__build__()
        self.my.Fr   = ports.OpticalPort(sname = 'Fr', pchain = lambda : self.Bk)
        self.my.Bk   = ports.OpticalPort(sname = 'Bk', pchain = lambda : self.Fr)
        return

    @declarative.mproperty
    def ports_optical(self):
        return (
            self.Fr,
            self.Bk,
        )

    def system_setup_ports(self, ports_algorithm):
        tmap = {
            self.Fr: self.Bk,
            self.Bk: self.Fr,
        }

        for port in self.ports_optical:
            for kfrom in ports_algorithm.port_update_get(port.i):
                #gets a passthrough always
                ports_algorithm.port_coupling_needed(tmap[port].o, kfrom)

                okey = kfrom[ports.OpticalFreqKey]
                ckey = kfrom[ports.ClassicalFreqKey]
                qkey = kfrom[ports.QuantumKey]
                barekey = kfrom.without_keys(ports.OpticalFreqKey, ports.ClassicalFreqKey, ports.QuantumKey)

                for kfrom2 in ports_algorithm.port_full_get(port.i):
                    barekey2 = kfrom2.without_keys(ports.OpticalFreqKey, ports.ClassicalFreqKey, ports.QuantumKey)
                    if barekey != barekey2:
                        continue

                    okey2 = kfrom2[ports.OpticalFreqKey]
                    ckey2 = kfrom2[ports.ClassicalFreqKey]
                    qkey2 = kfrom2[ports.QuantumKey]

                    if qkey2 == qkey:
                        #similar quantum keys means sum generation
                        okeyO = okey + okey2
                        ckeyO = ckey + ckey2
                    else:
                        #different keys implies difference generation
                        okeyO = okey - okey2
                        ckeyO = ckey - ckey2

                    if (
                        not self.system.reject_optical_frequency_order(okeyO)
                        and
                        not self.system.reject_classical_frequency_order(ckeyO)
                    ):
                        ports_algorithm.port_coupling_needed(
                            tmap[port].o,
                            barekey | ports.DictKey({
                                ports.OpticalFreqKey   : okeyO,
                                ports.ClassicalFreqKey : ckeyO,
                                ports.QuantumKey       : qkey
                            })
                        )

                    #in the difference case there can also be conjugate generation, so try the other difference as well
                    if qkey2 != qkey:
                        #different keys implies difference generation
                        okeyO = okey2 - okey
                        ckeyO = ckey2 - ckey
                        if (
                            not self.system.reject_optical_frequency_order(okeyO)
                            and
                            not self.system.reject_classical_frequency_order(ckeyO)
                        ):
                            #note using qkey2
                            ports_algorithm.port_coupling_needed(
                                tmap[port].o,
                                barekey | ports.DictKey({
                                    ports.OpticalFreqKey   : okeyO,
                                    ports.ClassicalFreqKey : ckeyO,
                                    ports.QuantumKey       : qkey2
                                })
                            )

            for kto in ports_algorithm.port_update_get(port.o):
                #just pass these to the input and it will deal with them
                ports_algorithm.port_coupling_needed(tmap[port].i, kto)
        return

    def system_setup_coupling(self, matrix_algorithm):
        tmap = {
            self.Fr: self.Bk,
            self.Bk: self.Fr,
        }

        for port in self.ports_optical:
            ddlt = collections.defaultdict(lambda : collections.defaultdict(list))
            out_map = dict()
            in_map = dict()
            portO = tmap[port]
            for kfrom in matrix_algorithm.port_set_get(port.i):
                #print("KFR: ", kfrom)
                okey = kfrom[ports.OpticalFreqKey]
                ckey = kfrom[ports.ClassicalFreqKey]
                qkey = kfrom[ports.QuantumKey]
                barekey = kfrom.without_keys(ports.OpticalFreqKey, ports.ClassicalFreqKey, ports.QuantumKey)

                if qkey == ports.LOWER[ports.QuantumKey]:
                    G = +self.symbols.i * self.nlg * self.length_mm.val
                else:
                    G = -self.symbols.i * self.nlg * self.length_mm.val

                for kfrom2 in matrix_algorithm.port_set_get(port.i):
                    #TODO could halve the number of ops here between these loops
                    barekey2 = kfrom2.without_keys(ports.OpticalFreqKey, ports.ClassicalFreqKey, ports.QuantumKey)
                    if barekey != barekey2:
                        continue

                    okey2 = kfrom2[ports.OpticalFreqKey]
                    ckey2 = kfrom2[ports.ClassicalFreqKey]
                    qkey2 = kfrom2[ports.QuantumKey]

                    if qkey2 == qkey:
                        #similar quantum keys means sum generation
                        okeyO = okey + okey2
                        ckeyO = ckey + ckey2
                    else:
                        #different keys implies difference generation
                        okeyO = okey - okey2
                        ckeyO = ckey - ckey2

                    kto = barekey | ports.DictKey({
                        ports.OpticalFreqKey   : okeyO,
                        ports.ClassicalFreqKey : ckeyO,
                        ports.QuantumKey       : qkey,
                    })

                    #print("KFR2: ", kfrom2)
                    #print("KTO: ", kto)
                    if kto in matrix_algorithm.port_set_get(portO.o):
                        F_list = list(okeyO.F_dict.items())
                        if len(F_list) > 1:
                            raise RuntimeError("Can't Currently do nonlinear optics on multiply composite wavelengths")
                        F, n = F_list[0]
                        ddlt[(port.i, kto)][(port.i, kfrom)].append(
                            (n * G, (port.i, kfrom2))
                        )
                        in_map[(port.i, kfrom)] = (port.i, kfrom)
                        out_map[(port.i, kto)] = (portO.o, kto)
                        #print("JOIN: ", kfrom, kfrom2, kto)

                    #in the difference case there can also be conjugate generation, so try the other difference as well
                    if qkey2 != qkey:
                        #note the reversal from above
                        okeyO = okey2 - okey
                        ckeyO = ckey2 - ckey
                        #note using qkey2 and negating the gain for the alternate out conjugation
                        kto = barekey | ports.DictKey({
                            ports.OpticalFreqKey   : okeyO,
                            ports.ClassicalFreqKey : ckeyO,
                            ports.QuantumKey       : qkey2,
                        })

                        if kto in matrix_algorithm.port_set_get(portO.o):
                            F_list = list(okeyO.F_dict.items())
                            if len(F_list) > 1:
                                raise RuntimeError("Can't Currently do nonlinear optics on multiply composite wavelengths")
                            F, n = F_list[0]

                            ddlt[(port.i, kto)][(port.i, kfrom)].append(
                                (-n * G, (port.i, kfrom2))
                            )
                            in_map[(port.i, kfrom)] = (port.i, kfrom)
                            out_map[(port.i, kto)] = (portO.o, kto)

            matrix_algorithm.injection_insert(
                ExpMatCoupling(
                    ddlt    = ddlt,
                    in_map  = in_map,
                    out_map = out_map,
                    N_ode   = self.N_ode,
                    order   = self.solution_order,
                )
            )
        return

