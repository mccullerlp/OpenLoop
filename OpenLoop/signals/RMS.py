# -*- coding: utf-8 -*-
"""
"""
from __future__ import division, print_function
#from OpenLoop.utilities.print import print
import declarative

#import numpy as np

#from numbers import Number
#import warnings

from . import bases
from . import ports


class MeanSquareMixer(bases.SignalElementBase):

    @declarative.dproperty
    def I(self, val = None):
        if val is None :
            return ports.SignalInPort()
        else:
            self.system.own_port_virtual(self, val.i)
            return val

    @declarative.dproperty
    def MS(self, val = None):
        if val is None :
            return ports.SignalOutPort()
        else:
            self.system.own_port_virtual(self, val.o)
            return val

    def system_setup_ports(self, ports_algorithm):
        #needs to isolate with list since port_coupling_needed is called on self.I.i
        for kfrom in list(ports_algorithm.port_update_get(self.I.i)):
            f_key = kfrom[ports.ClassicalFreqKey]
            kfromN = kfrom.replace_keys({ports.ClassicalFreqKey: -f_key})
            if self.system.reject_classical_frequency_order(-f_key):
                continue
            ports_algorithm.port_coupling_needed(self.I.i, kfromN)
        #only outputs the total MS at DC
        kto = ports.DictKey({ports.ClassicalFreqKey : ports.FrequencyKey({})})
        ports_algorithm.port_coupling_needed(self.MS.o, kto)
        return

    def system_setup_coupling(self, matrix_algorithm):
        kto = ports.DictKey({ports.ClassicalFreqKey : ports.FrequencyKey({})})
        already_keys = set()
        for kfromP in matrix_algorithm.port_set_get(self.I.i):
            if kfromP in already_keys:
                continue
            already_keys.add(kfromP)
            f_key = kfromP[ports.ClassicalFreqKey]
            if f_key.DC_is():
                matrix_algorithm.port_coupling_insert(
                    self.I.i, kfromP,
                    self.MS.o, kto,
                    1, (self.I.i, kfromP),
                )
            else:
                kfromN = kfromP.replace_keys({ports.ClassicalFreqKey: -f_key})
                already_keys.add(kfromN)
                if self.system.reject_classical_frequency_order(-f_key):
                    continue
                matrix_algorithm.nonlinear_triplet_insert(
                    pkfrom1 = (self.I.i, kfromP),
                    pkfrom2 = (self.I.i, kfromN),
                    pkto    = (self.MS.o, kto),
                    cplg    = 1 / 2,
                )
        return


class SquareRootFunction(bases.CouplerBase, bases.SystemElementBase):
    def __init__(
            self,
            **kwargs
    ):
        super(SquareRootFunction, self).__init__(**kwargs)
        self.I      = ports.SignalPortHolderIn()
        self.sqroot = ports.SignalOutPort()
        return

    def system_setup_ports(self, system):
        for kfrom in system.port_update_get(self.I.i):
            f_key = kfrom[ports.ClassicalFreqKey]
            kfromN = kfrom.replace_keys({ports.ClassicalFreqKey: -f_key})
            if system.reject_classical_frequency_order(-f_key):
                continue
            system.port_coupling_needed(self.I.i, kfromN)
        #only outputs the total RMS at DC
        kto = ports.DictKey({ports.ClassicalFreqKey : ports.FrequencyKey({})})
        system.port_coupling_needed(self.RMS.o, kto)
        return

    def system_setup_coupling(self, system):
        kto = ports.DictKey({ports.ClassicalFreqKey : ports.FrequencyKey({})})
        already_keys = set()
        for kfromP in system.port_set_get(self.I.i):
            if kfromP in already_keys:
                continue
            already_keys.add(kfromP)
            f_key = kfromP[ports.ClassicalFreqKey]
            if f_key.DC_is():
                system.port_coupling_insert(
                    self.I.i, kfromP,
                    self.RMS.o, kto,
                    1, (self.I.i, kfromP),
                )
            else:
                kfromN = kfromP.replace_keys({ports.ClassicalFreqKey: -f_key})
                already_keys.add(kfromN)
                if system.reject_classical_frequency_order(-f_key):
                    continue
                system.nonlinear_triplet_insert(
                    pkfrom1 = (self.I.i, kfromP),
                    pkfrom2 = (self.I.i, kfromN),
                    pkto    = (self.RMS.o, kto),
                    cplg    = 1 / 2,
                )
        return

class RMSMixer(bases.CouplerBase, bases.SystemElementBase):
    #TODO
    def __init__(
            self,
            **kwargs
    ):
        super(RMSMixer, self).__init__(**kwargs)
        self.I   = ports.SignalPortHolderIn(self,  x = 'I')
        self.RMS = SignalOutPort(sname = 'RMS')
        self.system.virtual_link
        raise NotImplementedError()
        return

    def system_setup_ports(self, system):
        for kfrom in system.port_update_get(self.I.i):
            f_key = kfrom[ports.ClassicalFreqKey]
            kfromN = kfrom.replace_keys({ports.ClassicalFreqKey: -f_key})
            if system.reject_classical_frequency_order(-f_key):
                continue
            system.port_coupling_needed(self.I.i, kfromN)
        #only outputs the total RMS at DC
        kto = ports.DictKey({ports.ClassicalFreqKey : ports.FrequencyKey({})})
        system.port_coupling_needed(self.RMS.o, kto)
        return

    def system_setup_coupling(self, system):
        kto = ports.DictKey({ports.ClassicalFreqKey : ports.FrequencyKey({})})
        already_keys = set()
        for kfromP in system.port_set_get(self.I.i):
            if kfromP in already_keys:
                continue
            already_keys.add(kfromP)
            f_key = kfromP[ports.ClassicalFreqKey]
            if f_key.DC_is():
                system.port_coupling_insert(
                    self.I.i, kfromP,
                    self.RMS.o, kto,
                    1, (self.I.i, kfromP),
                )
            else:
                kfromN = kfromP.replace_keys({ports.ClassicalFreqKey: -f_key})
                already_keys.add(kfromN)
                if system.reject_classical_frequency_order(-f_key):
                    continue
                system.nonlinear_triplet_insert(
                    (self.I.i, kfromP),
                    (self.I.i, kfromN),
                    (self.RMS.o, kto),
                    1 / 2,
                )
        return