# Copyright (C) 2012  Alex Nitz, Josh Willis, Andrew Miller
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.


#
# =============================================================================
#
#                                   Preamble
#
# =============================================================================
#
"""
This module provides classes that describe banks of waveforms
"""
from pycbc.types import zeros, TimeSeries, Array
from glue.ligolw import ligolw, table, lsctables, utils as ligolw_utils
import pycbc.waveform
from pycbc.filter import sigmasq
from pycbc import DYN_RANGE_FAC
import h5py


# dummy class needed for loading LIGOLW files
class LIGOLWContentHandler(ligolw.LIGOLWContentHandler):
    pass

lsctables.use_in(LIGOLWContentHandler)

class CachedFilterBank(object):
    def __init__(self, filename, cache_name, filter_length, delta_f, f_lower, dtype, psd):              
        self.filter_length = filter_length
        self.delta_f = delta_f
        self.f_lower = f_lower
        self.dtype = dtype
        self.psd = psd
        self.sigmasq_vec = None
        self.N = (filter_length - 1 ) * 2
        
        self.cache = h5py.File(cache_name)
    
        try:
            self.indoc = ligolw_utils.load_filename(
                filename, False, contenthandler=LIGOLWContentHandler)
            self.table = table.get_table(
                self.indoc, lsctables.SnglInspiralTable.tableName)
        except:
            self.table = []
            
    def __len__(self):
        return len(self.table)
        
    def __getitem__(self, index):
        template = TimeSeries(self.cache[str(index)][:], delta_t=1.0/4096, dtype=self.psd.dtype)
        template_size = len(template)
        template.resize(self.N)
        template.roll(-template_size)
        htilde = template.to_frequencyseries()
        htilde.resize(self.filter_length)
        htilde.sigmasq = sigmasq(htilde, self.psd, low_frequency_cutoff=self.f_lower)
        htilde.params = self.table[index]
        return htilde
        

class FilterBank(object):
    def __init__(self, filename, approximant, filter_length, delta_f, f_lower,
                 dtype, psd=None, out=None, **kwds):
        self.out = out
        self.dtype = dtype
        self.f_lower = f_lower
        self.approximant = approximant
        self.filename = filename
        self.delta_f = delta_f
        self.N = (filter_length - 1 ) * 2
        self.delta_t = 1.0 / (self.N * self.delta_f)
        self.filter_length = filter_length
        self.kmin = int(f_lower / delta_f)

        try:
            self.indoc = ligolw_utils.load_filename(
                filename, False, contenthandler=LIGOLWContentHandler)
            self.table = table.get_table(
                self.indoc, lsctables.SnglInspiralTable.tableName)
        except:
            self.table = []

        self.extra_args = kwds
        self.psd = psd

        #If we can for this template pregenerate the sigmasq vector
        self.sigmasq_vec = None
        if (psd is not None) and \
                pycbc.waveform.waveform_norm_exists(approximant):
            self.sigmasq_vec = pycbc.waveform.get_waveform_filter_norm(
                approximant, self.psd, filter_length,
                self.delta_f, self.f_lower)

    def __len__(self):
        return len(self.table)

    def __getitem__(self, index):
        # Make new memory for templates if we aren't given output memory
        if self.out is None:
            tempout = zeros(self.filter_length, dtype=self.dtype)
        else:
            tempout = self.out

        # Get the end of the waveform if applicable (only for SPAtmplt atm)
        f_end = pycbc.waveform.get_waveform_end_frequency(self.table[index],
                              approximant=self.approximant, **self.extra_args)

        if f_end is None or f_end >= (self.filter_length * self.delta_f):
            f_end = (self.filter_length-1) * self.delta_f

        poke  = tempout.data
        # Clear the storage memory
        tempout.clear()

        # Get the waveform filter
        distance = 1.0 / DYN_RANGE_FAC
        htilde = pycbc.waveform.get_waveform_filter(tempout[0:self.filter_length],
                            self.table[index], approximant=self.approximant,
                            f_lower=self.f_lower, delta_f=self.delta_f, delta_t=self.delta_t,
                            distance=distance, **self.extra_args)

        length_in_time = None
        if hasattr(htilde, 'length_in_time'):
            length_in_time = htilde.length_in_time

        # Make sure it is the desired type
        htilde = htilde.astype(self.dtype)

        htilde.end_frequency = f_end
        htilde.end_idx = int(htilde.end_frequency / htilde.delta_f)
        htilde.params = self.table[index]

        # If we were given a psd, calculate sigmasq so we have it for later
        if self.psd is not None:
            if self.sigmasq_vec is not None:

                # Get an amplitude normalization (mass dependant constant norm)
                amp_norm = pycbc.waveform.get_template_amplitude_norm(self.table[index],
                                  approximant=self.approximant, **self.extra_args)
                if amp_norm is None:
                    amp_norm = 1
                scale = DYN_RANGE_FAC * amp_norm

                htilde.sigmasq = self.sigmasq_vec[htilde.end_idx] * (scale) **2
            else:
                htilde.sigmasq = sigmasq(htilde, self.psd, low_frequency_cutoff=self.f_lower)
                
        if length_in_time is not None:
            htilde.length_in_time = length_in_time
            self.table[index].template_duration = length_in_time

        return htilde
