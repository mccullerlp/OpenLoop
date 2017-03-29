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
                newtup = [lt[0]]
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
        #pprint("PKS:")
        #pprint(pks)

    _prev_sol_vector = None

    def edge_func(self, pk_in, pk_out, sol_vector, sB):
        if sol_vector != self._prev_sol_vector:
            self._prev_sol_vector = sol_vector
            self.generate_solution(sol_vector)
        return self.solution.get((pk_in, pk_out), 0)

    def generate_solution(self, sol_vector):
        pks = self.pks
        pks_inv = self.pks_inv
        pkv = np.empty(len(pks), dtype=object)
        for idx, pk in enumerate(pks):
            #print("PK_G: ", (ins_p, pk))
            pkv[idx] = sol_vector.get(self.in_map[pk], 0)
        #print("PKV: ", pkv)

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

        eye = np.eye(len(pks))
        Mexp_tot = eye
        for idx_N in range(self.N_ode):
            m1 = np.zeros([len(pks), len(pks)], dtype = object)
            for (idx_out, idx_in), lt in self.ddlt_accel.items():
                    val = lt_val(lt)
                    m1[idx_out, idx_in] = val
            #print("M1: ", m1)
            m1 = m1 / self.N_ode
            Mexp = eye + m1
            mmem = m1
            for idx in range(1, self.order):
                mmem = (1 / (idx + 1)) * np.dot(m1, mmem)
                Mexp = Mexp + mmem
            Mexp_tot = np.dot(Mexp, Mexp_tot)
            #print(Mexp.shape, pkv.shape)
            pkv = np.dot(Mexp, pkv.reshape(-1, 1)).reshape(-1)
            #print("pkv2:", type(pkv), pkv.shape)
            #print(pkv)

        #print(m1)
        #print(Mexp)

        solution = dict()
        for idx_in in range(len(pks)):
            for idx_out in range(len(pks)):
                edge = Mexp_tot[idx_out, idx_in]
                if np.any(edge != 0):
                    pk_in = pks[idx_in]
                    pk_out = pks[idx_out]
                    #TODO: add debug config reference for this print
                    #if pk_in[ports.QuantumKey] != pk_out[ports.QuantumKey]:
                    #    print("SQZY: ", pk_in, pk_out, edge)
                    #else:
                    #    print(pk_in, pk_out, edge)
                #solution[(ins_p, pks[idx_in]), (outs_p, pks[idx_out])] = edge
                solution[self.in_map[pks[idx_in]], self.out_map[pks[idx_out]]] = edge

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
                        #TODO finish out_map logic
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

            ddlt2 = dict()
            for k, v in ddlt.items():
                v_ = dict()
                for k2, v2 in v.items():
                    v_[k2] = v2
                ddlt2[k] = v_
            #pprint(ddlt2)
            matrix_algorithm.injection_insert(
                ExpMatCoupling(
                    ddlt    = ddlt2,
                    in_map  = in_map,
                    out_map = out_map,
                    N_ode   = self.N_ode,
                    order   = self.solution_order,
                )
            )
        return


