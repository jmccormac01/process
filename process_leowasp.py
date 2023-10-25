"""
process_leowasp.py - Reduce and extract aperture photometry from LEOWASP

Use the common routines from JASTRO
"""
import os
import time
import warnings
import argparse as ap
from datetime import datetime
import numpy as np
import astropy.units as u
from astropy.wcs import FITSFixedWarning
from astropy.coordinates import EarthLocation
from donuts import Donuts
import jastro as j

# TODO: rolling shutter time correction

# ignore some annoying warnings
warnings.simplefilter('ignore', category=FITSFixedWarning)

# pylint: disable = invalid-name
# pylint: disable = redefined-outer-name
# pylint: disable = no-member
# pylint: disable = too-many-locals
# pylint: disable = too-many-arguments
# pylint: disable = unused-variable

def arg_parse():
    """
    Argument parser settings

    Parameters
    ----------
    None

    Returns
    -------
    args : array-like
        Array of command line arguments

    Raises
    ------
    None
    """
    p = ap.ArgumentParser()
    p.add_argument("night_config",
                   help="config file for this reduction")
    p.add_argument("instrument_config",
                   help="config file for this instrument")
    return p.parse_args()

if __name__ == '__main__':
    # parse the command line arguments
    args = arg_parse()
    # read in the config files
    night_config = j.config.load(args.night_config)
    inst_config = j.config.load(args.instrument_config)

    # set up DS9
    ds9 = night_config['ds9']
    if ds9:
        ds9_window_id = inst_config['ds9']['window_id']
        j.ds9.setup(ds9_window_id)
        draw_regions = True
    else:
        ds9_window_id = None
        draw_regions = False

    # set up the observatory EarthLocation
    location = EarthLocation(lat=inst_config['observatory']['olat']*u.deg,
                             lon=inst_config['observatory']['olon']*u.deg,
                             height=inst_config['observatory']['elev']*u.m)

    # set up the apertures for photometry
    x, y, rsi, rso = j.ds9.read_region_file(night_config['region_file'])
    # if not defocused, do some recentering
    if not night_config['defocused']:
        _, source_x, source_y, *_ = j.coords.source_extract(night_config['reference_image'],
                                                            inst_config['sky']['background_sigma'],
                                                            rad_sky_inner=rsi, rad_sky_outer=rso)
        x, y = j.coords.recenter_stars(x, y, source_x, source_y, night_config['max_sep_shift'])
    # otherwise leave apertures as manually placed

    # set up the reference image
    d = Donuts(night_config['reference_image'])

    # get list of all images
    images = j.housekeeping.get_image_list()

    # make master bias
    #master_bias = j.reduce.make_master_bias(images,
    #    bias_keyword=inst_config['imager']['bias_keyword'],
    #    master_bias_filename=night_config['master_bias_filename'])
    #if master_bias and ds9:
    #    j.ds9.display(ds9_window_id, night_config['master_bias_filename'])
    #    time.sleep(5)

    # make master dark
    master_dark, dark_exp = j.reduce.make_master_dark_osc(images,
        overscan_keyword=inst_config['imager']['overscan_keyword'],
        dark_keyword=inst_config['imager']['dark_keyword'],
        exptime_keyword=inst_config['imager']['exptime_keyword'],
        master_dark_filename=night_config['master_dark_filename'])
    if master_dark is not None and ds9:
        j.ds9.display(ds9_window_id, night_config['master_dark_filename'])
        time.sleep(5)

    # make master flat
    master_flat = j.reduce.make_master_flat_osc(images, night_config['filter'],
        overscan_keyword=inst_config['imager']['overscan_keyword'],
        master_dark=master_dark, dark_exp=dark_exp,
        flat_keyword=inst_config['imager']['flat_keyword'],
        exptime_keyword=inst_config['imager']['exptime_keyword'],
        master_flat_filename=night_config['master_flat_filename'])
    if master_flat is not None and ds9:
        j.ds9.display(ds9_window_id, night_config['master_flat_filename'])
        time.sleep(5)

    # reduce all the images and do the photometry
    for filename in images.files_filtered(imagetyp=inst_config['imager']['image_keyword'],
                                          filter=night_config['filter']):
        t1 = datetime.utcnow()
        if ds9:
            j.ds9.display(ds9_window_id, filename)
        # correct the times and reduce the images
        data, jd, bjd, hjd = j.reduce.correct_data_osc(filename, night_config['filter'],
            location, master_dark=master_dark,
            overscan_keyword=inst_config['imager']['overscan_keyword'],
            master_flat=master_flat, dark_exp=dark_exp,
            exptime_keyword=inst_config['imager']['exptime_keyword'],
            ra_keyword=inst_config['imager']['ra_keyword'],
            dec_keyword=inst_config['imager']['dec_keyword'],
            dateobs_start_keyword=inst_config['imager']['dateobs_start_keyword'])

        # inspect shifts between images
        shift = d.measure_shift(filename)
        sx = round(shift.x.value, 2)
        sy = round(shift.y.value, 2)
        # check for big shifts
        shifts = np.array([abs(sx), abs(sy)])
        if np.sum(shifts > night_config['max_donuts_shift']) > 0:
            print(f'{filename} image shift too big X: {sx} Y: {sy}')
            if not os.path.exists('failed_donuts'):
                os.mkdir('failed_donuts')
            comm = f'mv {filename} failed_donuts/'
            print(comm)
            os.system(comm)
            continue

        # do photometry on good images
        j.photometry.phot(data, shift, x, y, rsi, rso, night_config['aperture_radii'],
                          filename, jd, bjd, hjd, ds9_name=ds9_window_id,
                          gain=0.4, draw_regions=draw_regions,
                          index_offset=inst_config['ds9']['index_offset'])
        t2 = datetime.utcnow()
        print(t2-t1)
