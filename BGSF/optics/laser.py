# -*- coding: utf-8 -*-
"""
"""
from __future__ import (division, print_function)
import declarative as decl

from ..base.utilities import (
    type_test
)

from . import bases
from . import ports
from . import frequency
from . import vacuum
from . import standard_attrs


class Laser(
        bases.OpticalCouplerBase,
        bases.SystemElementBase
):

    @decl.dproperty
    def Fr(self):
        return ports.OpticalPortHolderInOut(sname = 'Fr')

    @decl.dproperty
    def polarization(self, val = 'S'):
        val = self.ooa_params.setdefault('polarization', val)
        return val

    power = standard_attrs.generate_power()

    @decl.dproperty
    def F(self, val):
        type_test(val, frequency.OpticalFrequency)
        return val

    @decl.dproperty
    def polk(self):
        if self.polarization == 'S':
            ret  = ports.PolS
        elif self.polarization == 'P':
            ret  = ports.PolP
        return ret

    @decl.dproperty
    def _fluct(self):
        #TODO add realistic laser noise
        return vacuum.OpticalVacuumFluctuation(port = self.Fr)

    phased = False
    multiple = 1

    @decl.dproperty
    def classical_fdict(self, val = None):
        if val is None:
            val = {}
        return val

    @decl.mproperty
    def optical_fdict(self):
        return {self.F : self.multiple}

    @decl.mproperty
    def fkey(self):
        return ports.DictKey({
            ports.OpticalFreqKey: ports.FrequencyKey(self.optical_fdict),
            ports.ClassicalFreqKey: ports.FrequencyKey(self.classical_fdict),
        })

    def system_setup_ports_initial(self, ports_algorithm):
        ports_algorithm.coherent_sources_needed(self.Fr.o, self.fkey | self.polk | ports.LOWER)
        ports_algorithm.coherent_sources_needed(self.Fr.o, self.fkey | self.polk | ports.RAISE)
        return

    def system_setup_ports(self, ports_algorithm):
        return

    def system_setup_coupling(self, matrix_algorithm):
        field_rtW = self.symbols.math.sqrt(self.power_W.val)
        if self.phased:
            matrix_algorithm.coherent_sources_insert(self.Fr.o, self.fkey | self.polk | ports.LOWER, field_rtW * self.symbols.i)
            matrix_algorithm.coherent_sources_insert(self.Fr.o, self.fkey | self.polk | ports.RAISE, -field_rtW * self.symbols.i)
        else:
            matrix_algorithm.coherent_sources_insert(self.Fr.o, self.fkey | self.polk | ports.LOWER, field_rtW)
            matrix_algorithm.coherent_sources_insert(self.Fr.o, self.fkey | self.polk | ports.RAISE, field_rtW)
        return

