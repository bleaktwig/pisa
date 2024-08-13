"""
A stage to handle atmospheric muon background systematics.
"""

from __future__ import absolute_import, print_function, division

import numpy as np
from scipy.interpolate import interp1d

from pisa.core.stage import Stage
from pisa.utils.resources import open_resource
from pisa.utils.profiler import profile

__all__ = ["atm_muons"]

__author__ = 'T. Stuttard, S. Wren, S. Mandalia'

class atm_muons(Stage):  # pylint: disable=invalid-name
    """
    PISA stage to apply atmospheric muon background systematics.
    Typically this is used with muons generated by MuonGun, but should be
    generic to other generators.
    Note that this stage only modifies an weights based on the systematics,
    it does not determine the nominal flux (this is assumed to either already
    available in the input files, or written by an upstream stage).

    Parameters
    ----------
    params : ParamSet or instantiable thereto
        Parameters for steering the stage. The following parameters must be included: .. ::

            atm_muon_scale : quantity (dimensionless)
                Normalisation of atmospheric muons
            delta_gamma_mu_file : str
                Path to file containing spectral index data
            delta_gamma_mu_spline_kind : str
                'kind' of spline, as per kwargs in scipy interp1d
            delta_gamma_mu_variable : str
                Name of variable in which the delta spectral index is splined
                Currently only supported variable is 'coszen'
            delta_gamma_mu : quantity (dimensionless)
                Parameter controlling variation in spectral index

    """

    def __init__(self,
                 input_names,
                 **std_kwargs,
                 ):

        expected_params = (
            'atm_muon_scale',
            'delta_gamma_mu_file',
            'delta_gamma_mu_spline_kind',
            'delta_gamma_mu_variable',
            'delta_gamma_mu'
        )

        # init base class
        super().__init__(
            expected_params=expected_params,
            **std_kwargs,
        )


    def setup_function(self):

        self.data.representation = self.calc_mode

        # Create the primary uncertainties spline that will be used for
        # re-weighting the muon flux
        self.prim_unc_spline = self._make_prim_unc_spline()

        # Get variable that the flux uncertainties are spline w.r.t
        rw_variable = self.params['delta_gamma_mu_variable'].value

        for container in self.data:
            # Get primary CR systematic spline
            container['rw_array'] = self.prim_unc_spline(container[rw_variable])

            # Reweighting term is positive-only by construction, so normalise
            # it by shifting the whole array down by a normalisation factor
            norm = container['rw_array'].sum() / container['rw_array'].size
            container['cr_rw_array'] = container['rw_array'] - norm


    @profile
    def apply_function(self):

        #self.data.representation = self.calc_mode

        # Apply muon normalisation/scaling
        atm_muon_scale = self.params['atm_muon_scale'].value.m_as("dimensionless")

        # Compute the weight modification due to the muon flux systematic
        cr_rw_scale = self.params['delta_gamma_mu'].value.m_as("dimensionless")

        # Write to the output container
        for container in self.data:
            weight_mod = 1 + (cr_rw_scale * container['cr_rw_array'])
            container['weights'] *= np.clip(weight_mod * atm_muon_scale, a_min=0, a_max=np.inf)


    def _make_prim_unc_spline(self):
        """
        Create the spline which will be used to re-weight muons based on the
        uncertainties arising from cosmic rays.
        Notes
        -----
        Details on this work can be found here -
        https://wiki.icecube.wisc.edu/index.php/DeepCore_Muon_Background_Systematics
        This work was done for the GRECO sample but should be reasonably
        generic. It was found to pretty much be a negligible systemtic. Though
        you should check both if it seems reasonable and it is still negligible
        if you use it with a different event sample.
        """
        # TODO(shivesh): "energy"/"coszen" on its own is taken to be the truth
        # TODO(shivesh): what does "true" muon correspond to - the deposited muon?
        # if 'true' not in self.params['delta_gamma_mu_variable'].value:
        #     raise ValueError(
        #         'Variable to construct spline should be a truth variable. '
        #         'You have put %s in your configuration file.'
        #         % self.params['delta_gamma_mu_variable'].value
        #     )


        # Get the variable which the atmopsheric muon uncertainty has been splined in
        bare_variable = self.params['delta_gamma_mu_variable'].value.split('true_')[-1] # Remove "truth_" part of variable name
        if not bare_variable == 'coszen':
            raise ValueError(
                'Muon primary cosmic ray systematic is currently only '
                'implemented as a function of cos(zenith). %s was set in the '
                'configuration file.'
                % self.params['delta_gamma_mu_variable'].value
            )
        if bare_variable not in self.params['delta_gamma_mu_file'].value:
            raise ValueError(
                'Variable set in configuration file is %s but the file you '
                'have selected, %s, does not make reference to this in its '
                'name.' % (self.params['delta_gamma_mu_variable'].value,
                           self.params['delta_gamma_mu_file'].value)
            )

        # Read the uncertainty data from the file
        uncdata = np.genfromtxt(
            open_resource(self.params['delta_gamma_mu_file'].value)
        ).T

        # Need to deal with zeroes that arise due to a lack of MC. For example,
        # in the case of the splines as a function of cosZenith, there are no
        # hoirzontal muons. Current solution is just to replace them with their
        # nearest non-zero values.
        while 0.0 in uncdata[1]:
            zero_indices = np.where(uncdata[1] == 0)[0]
            for zero_index in zero_indices:
                uncdata[1][zero_index] = uncdata[1][zero_index+1]

        # Add dummpy points for the edge of the zenith range
        xvals = np.insert(uncdata[0], 0, 0.0)
        xvals = np.append(xvals, 1.0)
        yvals = np.insert(uncdata[1], 0, uncdata[1][0])
        yvals = np.append(yvals, uncdata[1][-1])

        # Create the spline, using the 'kind' of interpolation specified by the user
        muon_uncf = interp1d(
            xvals,
            yvals,
            kind=self.params['delta_gamma_mu_spline_kind'].value
        )

        return muon_uncf
