#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2017, JK & JH
# Full license can be found in License.md
# -----------------------------------------------------------------------------
"""Wrapper for running sami2 model

Classes
-------------------------------------------------------------------------------
Model
    Loads, reshapes, and holds SAMI2 output for a given model run
    specified by the user.
-------------------------------------------------------------------------------


Moduleauthor
-------------------------------------------------------------------------------
Jeff Klenzing (JK), 1 Dec 2017, Goddard Space Flight Center (GSFC)
-------------------------------------------------------------------------------
"""
from os import path
import numpy as np
import xarray as xr
from sami2py.utils import generate_path, get_unformatted_data


class Model(object):
    """Python object to handle SAMI2 model output data
    """
    def __init__(self, tag, lon, year, day, outn=False, test=False):
        """ Loads a previously run sami2 model and sorts into
            appropriate array shapes

        Parameters
        ----------
        tag : (string)
            name of run (top-level directory)
        lon : (int)
            longitude reference
        year : (int)
            year
        day : (int)
            day of year from Jan 1
        outn : (boolean)
            if true : look for neutral density and wind files
            if false :  only look for default sami2 output
        test : (boolean)
            if true : use test model output
            if false : look for user made model output

        Returns
        -------
        self : model class object containing OCB file data

        Attributes
        ----------
        ut : (1D ndarray)
            Universal Time (hrs)
        slt : (1D ndarray)
            Solar Local Time (hr)

        glat : (2D ndarray)
            Geographic Latitude (deg)
        glon : (2D ndarray)
            Geographic Longitude (deg)
        zalt : (2D ndarray)
            Altitude (km)

        deni : (4D ndarray)
            Ion density by species (cm^-3)
        vsi : (4D ndarray)
            Ion Velocity by species (m/s)
        ti : (4D ndarray)
            Ion Temperature by species (K)
        te : (3D ndarray)
            Electron Temperature (K)

        Examples
        --------
        To load a previous model run:
            ModelRun = sami2py.Model(tag='run_name', lon=0, year=2012, day=210)

        """

        self.tag = tag
        self.lon0 = lon
        self.year = year
        self.day = day
        self.outn = outn
        self.test = test

        self._load_model()

    def __repr__(self):
        """Make a printable representation of a Model object

        Returns
        -------
        out : (string)
            string containing a printable representation of a Model object

        Examples
        --------
        Load the model
            ModelRun = sami2py.Model(tag='run_name', lon=0, year=2012, day=210)
        Check the model information
            ModelRun

        """

        out = ['']
        out.append('Model Run Name = ' + self.tag)
        out.append(('Day {day:03d}, {year:4d}').format(day=self.day,
                                                       year=self.year))
        out.append(('Longitude = {lon:d} deg').format(lon=self.lon0))
        temp_str = '{N:d} time steps from {t0:4.1f} to {tf:4.1f} UT'
        out.append(temp_str.format(N=len(self.ut),
                                   t0=min(self.ut),
                                   tf=max(self.ut)))
        out.append('Ions Used: ' + self.MetaData['Ions Used'])

        out.append('\nSolar Activity')
        out.append('--------------')
        temp_str = 'F10.7: {f107:5.1f} sfu'
        out.append(temp_str.format(f107=self.MetaData['F10.7']))
        temp_str = 'F10.7A: {f107a:5.1f} sfu'
        out.append(temp_str.format(f107a=self.MetaData['F10.7A']))
        out.append(('ap: {ap:d}').format(ap=self.MetaData['ap']))

        out.append('\nComponent Models Used')
        out.append('---------------------')
        out.append(' '.join(('Neutral Atmosphere:',
                             self.MetaData['Neutral Atmosphere Model'])))
        out.append('Winds: ' + self.MetaData['Wind Model'])
        out.append('Photoproduction: ' + self.MetaData['EUV Model'])
        out.append('ExB Drifts: ' + self.MetaData['ExB model'])

        mod_keys = self.check_standard_model()
        if mod_keys:
            out.append('\nMultipliers used')
            out.append('----------------')
            for mkey in mod_keys:
                out.append(('{s}: {f}').format(s=mkey,
                                               f=self.MetaData[mkey]))
        else:
            out.append('\nNo modifications to empirical models')

        return '\n'.join(out)

    def _calculate_slt(self):
        """Calculates Solar Local Time for reference point of model

        Returns
        -------
        self.slt : (float)
            Solar Local Time in hours
        """

        local_time = np.mod((self.ut * 60 + self.lon0 * 4), 1440) / 60.0
        mean_anomaly = 2 * np.pi * self.day / 365.242
        delta_t = (-7.657 * np.sin(mean_anomaly)
                   + 9.862 * np.sin(2 * mean_anomaly + 3.599))
        self.slt = local_time - delta_t / 60.0

    def _load_model(self):
        """Loads model results

        Returns
        -------
        void
            Model object modified in place
        """

        nf = 98
        nz = 101
        ni = 7
        
        def return_fourier(x, coeffs):
            """
            Returns a Fourier series up to NumF coefficients
            """
            def cos_a(x, n):
                """simple cosine"""
                return np.cos(n * np.pi * x / 12.0)
        
            def sin_a(x, n):
                """simple sine"""
                return np.sin(n * np.pi * x / 12.0)
        
            NumF = int((len(coeffs) - 1)/2)
        
            y = coeffs[0]
            for i in range(1, NumF+1):
                y = y + coeffs[2*i-1]*cos_a(x, i) + coeffs[2*i]*sin_a(x, i)
        
            return y
        
        model_path = generate_path(self.tag, self.lon0, self.year, self.day,
                                   self.test)

        # Get NameList
        namelist_file = open(path.join(model_path, 'sami2py-1.00.namelist'))
        self.namelist = namelist_file.readlines()
        namelist_file.close()

        self.MetaData = dict()
        self._generate_metadata(self.namelist)

        # Get times
        time = np.loadtxt(path.join(model_path, 'time.dat'))
        self.ut = time[:, 1] + time[:, 2] / 60 + time[:, 3] / 3600

        self._calculate_slt()
        nt = len(self.ut)

        if self.MetaData['fmtout']:
            # Get Location
            glat = np.loadtxt(path.join(model_path, 'glatf.dat'))
            glon = np.loadtxt(path.join(model_path, 'glonf.dat'))
            zalt = np.loadtxt(path.join(model_path, 'zaltf.dat'))

            # Get plasma values
            deni = np.loadtxt(path.join(model_path, 'denif.dat'))
            vsi = np.loadtxt(path.join(model_path, 'vsif.dat'))
            ti = np.loadtxt(path.join(model_path, 'tif.dat'))
            te = np.loadtxt(path.join(model_path, 'tef.dat'))

            # get neutral values
            if self.outn:
                denn = np.loadtxt(path.join(model_path, 'dennf.dat'))
                u4 = np.loadtxt(path.join(model_path, 'u4f.dat'))
        else:
            # Get Location
            glat = get_unformatted_data(model_path, 'glat')
            glon = get_unformatted_data(model_path, 'glon')
            zalt = get_unformatted_data(model_path, 'zalt')

            # Get plasma values
            dim0 = nz * nf * ni + 2
            dim1 = nt
            deni = get_unformatted_data(model_path, 'deni',
                                        dim=(dim0, dim1), reshape=True)
            vsi = get_unformatted_data(model_path, 'vsi',
                                       dim=(dim0, dim1), reshape=True)
            ti = get_unformatted_data(model_path, 'ti',
                                      dim=(dim0, dim1), reshape=True)

            # Electron Temperatures have only one species
            dim0 = nz * nf + 2
            te = get_unformatted_data(model_path, 'te',
                                      dim=(dim0, dim1), reshape=True)
            if self.outn:
                # Multiple neutral species
                dim0 = nz * nf * ni + 2
                denn = get_unformatted_data(model_path, 'denn',
                                            dim=(dim0, dim1), reshape=True)
                # Only one wind
                dim0 = nz * nf + 2
                u4 = get_unformatted_data(model_path, 'u4',
                                          dim=(dim0, dim1), reshape=True)

        glat = np.reshape(glat, (nz, nf), order="F")
        glon = np.reshape(glon, (nz, nf), order="F")
        zalt = np.reshape(zalt, (nz, nf), order="F")
        deni = np.reshape(deni, (nz, nf, ni, nt), order="F")
        vsi = np.reshape(vsi, (nz, nf, ni, nt), order="F")
        ti = np.reshape(ti, (nz, nf, ni, nt), order="F")
        te = np.reshape(te, (nz, nf, nt), order="F")
        self.data = xr.Dataset({'deni': (['z', 'f', 'ion', 'ut'], deni),
                                'vsi': (['z', 'f', 'ion', 'ut'], vsi),
                                'ti': (['z', 'f', 'ion', 'ut'], ti),
                                'te': (['z', 'f', 'ut'], te),
                                'slt': (['ut'], self.slt)},
                               coords={'glat': (['z', 'f'], glat),
                                       'glon': (['z', 'f'], glon),
                                       'zalt': (['z', 'f'], zalt),
                                       'ut': self.ut})
        if self.outn:
            denn = np.reshape(denn, (nz, nf, ni, nt), order="F")
            self.data['denn'] = (('z', 'f', 'ion', 'ut'), denn)
            u4 = np.reshape(u4, (nz, nf, nt), order="F")
            self.data['u4'] = (('z', 'f', 'ut'), u4)
        
        # Add drifts
        if self.MetaData['ExB model'] == 'Fourier Series': 
            self.data['ExB'] = return_fourier(self.data['slt'],
                                              self.MetaData['Fourier Coeffs'])

    def _generate_metadata(self, namelist):
        """Reads the namelist and generates MetaData based on Parameters

        Parameters
        -----------
        namelist : (list)
            variable namelist from SAMI2 model

        Returns
        -------
        void
            Model object modified in place
        """

        import re

        def find_float(name, ind):
            """regular expression search for float vals"""
            return float(re.findall(r"\d*\.\d+|\d+", name)[ind])

        def find_int(name, ind):
            """regular expression search for int vals"""
            return int(re.findall(r"\d+", name)[ind])

        self.MetaData['fmtout'] = ('.true.' in namelist[1])

        self.MetaData['F10.7A'] = find_float(namelist[14], 0)
        self.MetaData['F10.7'] = find_float(namelist[15], 2)
        self.MetaData['ap'] = find_int(namelist[16], 0)

        self.MetaData['Neutral Atmosphere Model'] = 'NRLMSISe-2000'
        self.MetaData['EUV Model'] = 'EUVAC'

        # Ions Used
        nion1 = wind_model = find_int(namelist[20], 1) - 1
        nion2 = wind_model = find_int(namelist[21], 1) - 1
        ions = ['H+', 'O+', 'NO+', 'O2+', 'He+', 'N2+', 'N+']
        self.MetaData['Ions Used'] = ', '.join(ions[nion1:nion2])

        # Multipliers
        neutral_scalars = re.findall(r"\d*\.\d+|\d+", namelist[28])
        self.MetaData['H Multiplier'] = float(neutral_scalars[0])
        self.MetaData['O Multiplier'] = float(neutral_scalars[1])
        self.MetaData['NO Multiplier'] = float(neutral_scalars[2])
        self.MetaData['O2 Multiplier'] = float(neutral_scalars[3])
        self.MetaData['He Multiplier'] = float(neutral_scalars[4])
        self.MetaData['N2 Multiplier'] = float(neutral_scalars[5])
        self.MetaData['N Multiplier'] = float(neutral_scalars[6])
        self.MetaData['T_exo Multiplier'] = find_float(namelist[33], 0)
        self.MetaData['T_n Multiplier'] = find_float(namelist[29], 0)
        self.MetaData['EUV Multiplier'] = find_float(namelist[34], 0)
        self.MetaData['ExB Drift Multiplier'] = find_float(namelist[24], 1)
        self.MetaData['Wind Multiplier'] = find_float(namelist[23], 1)

        if '.true.' in namelist[10]:
            self.MetaData['ExB model'] = 'Fejer-Scherliess'
        else:
            model_path = generate_path(self.tag, self.lon0, self.year,
                                       self.day, self.test)
            self.MetaData['ExB model'] = 'Fourier Series'
            self.MetaData['Fourier Coeffs'] = np.loadtxt(path.join(model_path,
                                                                   'exb.inp'))

        wind_model = find_int(namelist[35], 0)
        self.MetaData['Wind Model'] = ('HWM-{:02d}').format(wind_model)

        # Model Geometry
        self.MetaData['rmin'] = find_float(namelist[11], 0)
        self.MetaData['rmax'] = find_float(namelist[12], 0)
        self.MetaData['gams'] = find_int(namelist[26], 0)
        self.MetaData['gamp'] = find_int(namelist[27], 0)
        self.MetaData['altmin'] = find_float(namelist[13], 0)

        # Model runtime
        self.MetaData['dthr'] = find_float(namelist[5], 0)
        self.MetaData['hrinit'] = find_float(namelist[22], 0)
        self.MetaData['hrpr'] = find_float(namelist[6], 0)
        self.MetaData['hrmax'] = find_float(namelist[3], 0)
        self.MetaData['dt0'] = find_float(namelist[4], 0)
        self.MetaData['maxstep'] = find_int(namelist[2], 0)
        self.MetaData['denmin'] = find_float(namelist[30], 0)

    def check_standard_model(self, model_type="all"):
        """Checks for standard atmospheric inputs

        Parameters
        ----------
        model_type : (str)
            Limit check to certain models (default='all')
            Not currently implemented

        Returns
        -------
        mod_keys : (list)
            List of modified keyword for self.MetaData, empty
            if no modifications were made

        Examples
        --------
        Load the model
            ModelRun = sami2py.Model(tag='run_name', lon=0, year=2012, day=210)
        Check the model information for changes to the standard inputs
            ModelRun.check_standard_model()

        """
        mod_keys = list()
        meta_keys = list(self.MetaData.keys())

        # See if Fourier Coefficients are used
        mkey = 'Fourier Coeffs'
        if mkey in meta_keys:
            mod_keys.append(mkey)
            # Since this item is an array, remove for multiplier check
            meta_keys.remove(mkey)

        # Check for scalar multipliers
        for mkey in meta_keys:
            if ((mkey.find('Multiplier') > 0) & (self.MetaData[mkey] != 1)):
                mod_keys.append(mkey)

        return mod_keys

    def plot_lat_alt(self, time_step=0, species=1):
        """Plots input parameter as a function of latitude and altitude

        Parameters
        ----------
        time_step : (int)
            time index for SAMI2 model results
        species : (int)
            ion species index :
            0: H+, 1: O+, 2: NO+, 3: O2+, 4: He+, 5: N2+, 6: N+

        Examples
        --------
        Load the model
            ModelRun = sami2py.Model(tag='run_name', lon=0, year=2012, day=210)
        Plot the O+ density at the beginning of the model
            ModelRun.plot_lat_alt()
        Plot the H+ density at the 100th time step (initial step is 0)
            ModelRun.plot_lat_alt(time_step=99, species=0)

        """
        import matplotlib.pyplot as plt
        import warnings

        warnings.warn(' '.join(["Model.plot_lat_alt is deprecated and will be",
                                "removed in a future version. ",
                                "Use sami2py_vis instead"]),
                      DeprecationWarning)

        fig = plt.gcf()
        plt.pcolor(self.data['glat'], self.data['zalt'],
                   self.data['deni'][:, :, species, time_step])
        plt.xlabel('Geo Lat (deg)')
        plt.ylabel('Altitude (km)')

        return fig
