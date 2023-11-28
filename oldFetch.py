#!/usr/bin/env python3
# LeCrunch3
# Copyright (C) 2021 Nicola Minafra
#
# based on
#
# LeCrunch2
# Copyright (C) 2014 Benjamin Land
#
# based on
#
# LeCrunch
# Copyright (C) 2010 Anthony LaTorre
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import time
import string
import struct
import socket
import h5py
import numpy as np
from LeCrunch3 import LeCrunch3


def fetchAndSaveFast(filename, nevents, nsequence, ip, timeout=1000, b16acq=True):
    """
    Fetch and save waveform traces from the oscilloscope
    with ADC values and with all info needed to reconstruct the waveforms
    It is faster than fetchAndSaveSimple but it requires a bit more code to analyze the files
    """
    startTime = time.time()
    scope = LeCrunch3(ip, timeout=timeout)
    scope.clear()
    scope.set_sequence_mode(nsequence)
    if b16acq:
        scopeSets = scope.get_settings()

        for k, v in scopeSets.items():
            scopeSets[k] = v.decode()
        scopeSets["COMM_FORMAT"] = "CFMT DEF9,WORD,BIN"

        scope.set_settings(scopeSets)

    channels = scope.get_channels()
    settings = scope.get_settings()

    if b"ON" in settings["SEQUENCE"]:
        sequence_count = int(settings["SEQUENCE"].split(b",")[1])
    else:
        sequence_count = 1
    # print(sequence_count)

    if nsequence != sequence_count:
        print("Could not configure sequence mode properly")
    if sequence_count != 1:
        print(f"Using sequence mode with {sequence_count} traces per aquisition")

    f = h5py.File(filename, "w")
    for command, setting in settings.items():
        f.attrs[command] = setting
    current_dim = {}

    print("Channels: ", channels)
    for channel in channels:
        wave_desc = scope.get_wavedesc(channel)
        current_dim[channel] = wave_desc["wave_array_count"] // sequence_count
        f.create_dataset(
            f"c{channel}_samples", (nevents, current_dim[channel]), dtype=wave_desc["dtype"], maxshape=(nevents, None)
        )
        ## Save  attributes in the file
        for key, value in wave_desc.items():
            try:
                f["c%i_samples" % channel].attrs[key] = value
            except ValueError:
                pass
        f.create_dataset("c%i_vert_offset" % channel, (nevents,), dtype="f8")
        f.create_dataset("c%i_vert_scale" % channel, (nevents,), dtype="f8")
        f.create_dataset("c%i_horiz_offset" % channel, (nevents,), dtype="f8")
        f.create_dataset("c%i_horiz_scale" % channel, (nevents,), dtype="f8")
        f.create_dataset("c%i_trig_offset" % channel, (nevents,), dtype="f8")
        f.create_dataset("c%i_trig_time" % channel, (nevents,), dtype="f8")
    f.create_dataset("seconds_from_start", (nevents,), dtype="f8")

    try:
        i = 0
        while i < nevents:
            print(f"\rSCOPE: fetching event: {i}")
            sys.stdout.flush()
            try:
                f[f"seconds_from_start"][i] = float(time.time() - startTime)
                scope.trigger()
                for channel in channels:
                    wave_desc, trg_times, trg_offsets, wave_array = scope.get_waveform_all(channel)
                    num_samples = wave_desc["wave_array_count"] // sequence_count
                    num_samples_toSave = int(1 * num_samples)  ##TORemove
                    if current_dim[channel] < num_samples_toSave:
                        current_dim[channel] = num_samples_toSave
                        f[f"c{channel}_samples"].resize(current_dim[channel], 1)
                    traces = wave_array.reshape(sequence_count, wave_array.size // sequence_count)
                    # necessary because h5py does not like indexing and this is the fastest (and man is it slow) way
                    scratch = np.zeros((current_dim[channel],), dtype=wave_array.dtype)
                    for n in range(0, sequence_count):
                        scratch[0:num_samples] = traces[n][:num_samples_toSave]
                        f[f"c{channel}_samples"][i + n] = scratch
                        f["c%i_vert_offset" % channel][i + n] = wave_desc["vertical_offset"]
                        f["c%i_vert_scale" % channel][i + n] = wave_desc["vertical_gain"]
                        f["c%i_horiz_offset" % channel][i + n] = wave_desc["horiz_offset"]
                        f["c%i_horiz_scale" % channel][i + n] = wave_desc["horiz_interval"]
                        f["c%i_trig_offset" % channel][i + n] = trg_offsets[n]
                        f["c%i_trig_time" % channel][i + n] = trg_times[n]

            except Exception as e:
                print("Error\n" + str(e))
                scope.clear()
                scope.set_settings(scopeSets)
                continue
            i += sequence_count
    except:
        print("\rUser interrupted fetch early or something happened...")
    finally:
        print(
            "Closing the file\r",
        )
        f.close()
        scope.clear()
        return i


if __name__ == "__main__":
    import optparse

    usage = "usage: %prog <filename/prefix> [-n] [-s]"
    parser = optparse.OptionParser(usage, version="%prog 0.1.0")
    parser.add_option("-i", type="str", dest="ip", help="IP address of the scope", default="127.0.0.1")
    parser.add_option("-n", type="int", dest="nevents", help="number of events to capture in total", default=1000)
    parser.add_option(
        "-s", type="int", dest="nsequence", help="number of sequential events to capture at a time", default=1
    )
    parser.add_option("--time", action="store_true", dest="time", help="append time string to filename", default=False)
    (options, args) = parser.parse_args()

    if len(args) < 1:
        sys.exit(parser.format_help())

    if options.nevents < 1 or options.nsequence < 1:
        sys.exit("Arguments to -s or -n must be positive")

    filename = (
        args[0] + time.strftime("_%d_%b_%Y_%H:%M:%S", time.localtime()) + ".h5" if options.time else args[0] + ".h5"
    )
    print(f"Saving to file {filename}")

    start = time.time()
    count = fetchAndSaveFast(filename, options.nevents, options.nsequence, options.ip)
    elapsed = time.time() - start
    if count > 0:
        print(f"Completed {count} events in {elapsed:.3f} seconds.")
        print(f"Averaged {elapsed/count:.5f} seconds per acquisition.")
