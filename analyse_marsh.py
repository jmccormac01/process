"""
analyse_marsh.py - Analyse aperture photometry from process

Use the common routines from JASTRO
"""
import sys
import argparse as ap
import numpy as np
import pandas as pd
import jastro as j

# phot settings
N_PHOT_OUTPUT_COLS = 7
N_PRE_PHOT_COLS = 4

def arg_parse():
    """
    Argument parser for analysis script

    Parameters
    ----------
    None

    Returns
    -------
    args : array-like
        parsed arguments object

    Raises
    ------
    None
    """
    p = ap.ArgumentParser()
    p.add_argument("night_config",
                   help="config file for this reduction")
    p.add_argument("instrument_config",
                   help="config file for this instrument")
    p.add_argument('phot_file',
                   help="Photometry file to plot")
    p.add_argument('--output',
                   help='output final light curve',
                   action="store_true")
    p.add_argument('--checks',
                   help='plot comparison star checks?',
                   action='store_true')
    p.add_argument('--fittype',
                   help='Order of polynomial fit to OOT data',
                   choices=[-1, 0, 1, 2],
                   type=int,
                   default=1)
    return p.parse_args()

if __name__ == "__main__":
    # psrse the command line arguments
    args = arg_parse()

    # read in the config files
    night_config = j.config.load(args.night_config)
    inst_config = j.config.load(args.instrument_config)

    # get the aperture radius and filter
    print(f'Plotting from photometry {args.phot_file}...')
    aperture_radius = args.phot_file.split('phot')[1]
    filt = night_config['filter']
    bin_fact = night_config['binning']
    fit_type = night_config['fit_type']
    fit_low = night_config['fit_parameters'][0]
    fit_high = night_config['fit_parameters'][1]

    # load the photometry file
    try:
        lcs = pd.read_csv(args.phot_file, header=None, skiprows=0, delim_whitespace=True)
        n_comp_stars = ((len(lcs.columns)-N_PRE_PHOT_COLS)//N_PHOT_OUTPUT_COLS) - 1
    except FileNotFoundError:
        print('File not found {args.phot_file}...')
        sys.exit(1)

    # select the different times
    filenames = list(lcs[0])
    jd = np.array(lcs[1])
    bjd = np.array(lcs[2])
    hjd = np.array(lcs[3])
    # trim integer days for now, easier to plot etc
    jd0 = int(jd[0])
    jd = jd - jd0
    bjd = bjd - jd0
    hjd = hjd - jd0

    # get all the comparisons into a stackable numpy array
    # make a check on the comparison stars before continuing
    stack, stack_max_pix, stack_sky = [], [], []
    for i in range(1, n_comp_stars+1):
        stack.append(np.array(lcs[N_PRE_PHOT_COLS + (N_PHOT_OUTPUT_COLS*i - 5)]))
        stack_sky.append(np.array(lcs[N_PRE_PHOT_COLS + (N_PHOT_OUTPUT_COLS*i - 3)]))
        stack_max_pix.append(np.array(lcs[N_PRE_PHOT_COLS + (N_PHOT_OUTPUT_COLS*i - 1)]))
    comparisons_max_pix = np.vstack(stack_max_pix)
    comparisons = np.vstack(stack)
    comparison = np.sum(comparisons, axis=0)
    comparisons_sky = np.vstack(stack_sky)
    # take the errors as just star + sky for now
    comparisons_err = np.sqrt(comparisons_sky)
    comparison_err = np.sqrt(np.sum(comparisons_err**2, axis=0))

    # get the target values
    target = np.array(lcs[N_PRE_PHOT_COLS + N_PHOT_OUTPUT_COLS*(n_comp_stars+1) - 5])
    target_sky = np.array(lcs[N_PRE_PHOT_COLS + N_PHOT_OUTPUT_COLS*(n_comp_stars+1) - 3])
    target_max_pix = np.array(lcs[N_PRE_PHOT_COLS + N_PHOT_OUTPUT_COLS*(n_comp_stars+1) - 1])
    # take the errors as just star + sky for now
    target_err = np.sqrt(target_sky)

    if args.checks:
        # plot the maximium pixel values
        j.plots.plot_max_pixel_values(jd, comparisons_max_pix, target_max_pix)
        # plot the comparisons
        j.plots.plot_comparison_stars(jd, comparisons)
        # plot the raw fluxes
        j.plots.plot_star_fluxes(jd, comparisons, target, aperture_radius)

    # get error on transit from quotiant rule for errors
    lightcurve = target/comparison
    dx = target_err/target
    dy = comparison_err/comparison
    lightcurve_err = np.sqrt((dx**2)+(dy**2)) * lightcurve

    # get some target info
    target_id = j.housekeeping.get_target_id(night_config['reference_image'],
                                             inst_config['imager']['object_keyword'])
    night_id = j.housekeeping.get_night_id(night_config['reference_image'],
                                           inst_config['imager']['dateobs_start_keyword'])
    # normalise the light curve
    lightcurve_n, lightcurve_err_n, bjd_b, lightcurve_nb, lightcurve_err_nb = j.lightcurves.normalise(filt,
        bjd, jd0, lightcurve, lightcurve_err, aperture_radius, bin_fact, target_id,
        night_id, fit_type=fit_type, fit_low=fit_low, fit_high=fit_high)

    # convert normalised lc to mags
    mags, mags_err = j.lightcurves.flux_to_mags(lightcurve_n, lightcurve_err_n)

    # generate output files here
    if args.output:
        # unbinned
        outname = f'{target_id}_{filt}_{night_id}_F{args.fittype}_A{aperture_radius}.lc.txt'
        np.savetxt(outname,
                   np.c_[jd+jd0, hjd+jd0, bjd+jd0, lightcurve_n, lightcurve_err_n, mags, mags_err],
                   fmt='%.8f  %.8f  %.8f  %.4f  %.4f  %.4f  %.4f',
                   header='JD-MID  HJD-MID  BJD_TDB-MID  FLUX  FLUX_ERR  MAG  MAG_ERR')
        # binned
        outname_b = f'{target_id}_{filt}_{night_id}_F{args.fittype}_A{aperture_radius}_b{bin_fact}.lc.txt'
        np.savetxt(outname_b,
                   np.c_[bjd_b+jd0, lightcurve_nb, lightcurve_err_nb],
                   fmt='%.8f  %.4f  %.4f',
                   header='BJD_TDB-MID  FLUX  FLUX_ERR')
