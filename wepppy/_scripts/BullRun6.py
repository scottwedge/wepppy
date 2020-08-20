import os
import sys

import shutil
from os.path import exists as _exists
from os.path import split as _split
from pprint import pprint
from time import time
from time import sleep
from copy import deepcopy

import wepppy

from wepppy.all_your_base import isfloat
from wepppy.soils.utils import modify_ksat
from wepppy.nodb import *
from os.path import join as _join
from wepppy.wepp.out import TotalWatSed
from wepppy.export import arc_export

from wepppy.climates.cligen import ClimateFile

from wepppy.nodb.mods.portland.livneh_daily_observed import LivnehDataManager
from wepppy.nodb.mods.portland.bedrock import ShallowLandSlideSusceptibility, BullRunBedrock

from osgeo import gdal, osr
gdal.UseExceptions()

from wepppy._scripts.utils import *

os.chdir('/geodata/weppcloud_runs/')

wd = None


def log_print(*msg):
    now = datetime.now()
    print('[{now}] {wd}: {msg}'.format(now=now, wd=wd, msg=', '.join(str(v) for v in msg)))


if __name__ == '__main__':

    lvdm = LivnehDataManager()

    # Run 1 - Daymet (adjust for <2005 and runoff/pp ratio) + shallow groundwater + pmetpara
    # Run 2 - Daymet (adjust for <2005 and runoff/pp ratio) + shallow landslides + pmetpara
    # Run 3 - GridMet (adjust for runoff/pp ratio) + shallow groundwater + pmetpara
    # Run 4 - GridMet (adjust for runoff/pp ratio) + shallow landslides + pmetpara

    precip_transforms = {
        'gridmet': {
            'SmallTest': 1.068883117,
            'SouthFork': 1.068883117,
            'CedarCreek': 1.120768995,
            'BlazedAlder': 1.098866242,
            'FirCreek': 0.916802717,
            'BRnearMultnoma': 1.180931876,
            'NorthFork': 1.267197533,
            'LittleSandy': 1.007254747,
        },
        'daymet': {
            'SmallTest': 1.100579816,
            'SouthFork': 1.100579816,
            'CedarCreek': 1.221992293,
            'BlazedAlder': 1.067938504,
            'FirCreek': 0.885748368,
            'BRnearMultnoma': 1.254837877,
            'NorthFork': 1.180883364,
            'LittleSandy': 1.008756432,
        }
    }


    def _daymet_cli_adjust(cli_dir, cli_fn, watershed):
        cli = ClimateFile(_join(cli_dir, cli_fn))

        cli.discontinuous_temperature_adjustment(datetime.date(2005, 11, 2))

        pp_scale = precip_transforms['daymet'][watershed]
        cli.transform_precip(offset=0, scale=pp_scale)

        cli.write(_join(cli_dir, 'adj_' + cli_fn))

        return 'adj_' + cli_fn


    def _gridmet_cli_adjust(cli_dir, cli_fn, watershed):
        cli = ClimateFile(_join(cli_dir, cli_fn))

        pp_scale = precip_transforms['gridmet'][watershed]
        cli.transform_precip(offset=0, scale=pp_scale)

        cli.write(_join(cli_dir, 'adj_' + cli_fn))

        return 'adj_' + cli_fn


    watersheds = [
        dict(watershed='SouthFork',
            extent=[-122.22908020019533, 45.268121280142886, -121.74842834472658, 45.60539133629575],
            map_center=[-121.98875427246095, 45.43700828867391],
            map_zoom=11,
            outlet=[-122.1083333, 45.444722],
            landuse=None,
            cs=150, erod=0.000001,
            csa=10, mcl=100,
	    surf_runoff=0.003, lateral_flow=0.004, baseflow=0.005, sediment=1000.0,
            gwstorage=100, bfcoeff=0.04, dscoeff=0.00, bfthreshold=1.001,
            mid_season_crop_coeff=0.80, p_coeff=0.80),
        dict(watershed='CedarCreek',
            extent=[-122.22908020019533, 45.268121280142886, -121.74842834472658, 45.60539133629575],
            map_center=[-121.98875427246095, 45.43700828867391],
            map_zoom=11,
            outlet=[-122.03486546021158, 45.45789702345389],
            landuse=None,
            cs=110, erod=0.000001,
            csa=10, mcl=100,
	    surf_runoff=0.003, lateral_flow=0.004, baseflow=0.005, sediment=1000.0,
            gwstorage=100, bfcoeff=0.04, dscoeff=0.00, bfthreshold=1.001,
            mid_season_crop_coeff=1.2, p_coeff=1.2),
        dict(watershed='BlazedAlder',
            extent=[-122.22908020019533, 45.268121280142886, -121.74842834472658, 45.60539133629575],
            map_center=[-121.98875427246095, 45.43700828867391],
            map_zoom=11,
            outlet=[-121.89124077457025, 45.45220046527376],
            landuse=None,
            cs=50, erod=0.000001,
            csa=10, mcl=100,
	    surf_runoff=0.003, lateral_flow=0.004, baseflow=0.005, sediment=1000.0,
            gwstorage=100, bfcoeff=0.04, dscoeff=0.00, bfthreshold=1.001,
            mid_season_crop_coeff=0.80, p_coeff=0.80),
        dict(watershed='FirCreek',
            extent=[-122.22908020019533, 45.268121280142886, -121.74842834472658, 45.60539133629575],
            map_center=[-121.98875427246095, 45.43700828867391],
            map_zoom=11,
            outlet=[-122.02581486422827, 45.47989113970676],
            landuse=None,
            cs=150, erod=0.000001,
            csa=10, mcl=100,
	    surf_runoff=0.003, lateral_flow=0.004, baseflow=0.005, sediment=1000.0,
            gwstorage=100, bfcoeff=0.04, dscoeff=0.00, bfthreshold=1.001,
            mid_season_crop_coeff=0.80, p_coeff=0.80),
        dict(watershed='BRnearMultnoma',
            extent=[-122.22908020019533, 45.268121280142886, -121.74842834472658, 45.60539133629575],
            map_center=[-121.98875427246095, 45.43700828867391],
            map_zoom=11,
            outlet=[-122.01099283401598, 45.498468197226025],
            landuse=None,
            cs=200, erod=0.000001,
            csa=10, mcl=100,
	    surf_runoff=0.003, lateral_flow=0.004, baseflow=0.005, sediment=1000.0,
            gwstorage=100, bfcoeff=0.04, dscoeff=0.00, bfthreshold=1.001,
            mid_season_crop_coeff=1.2, p_coeff=1.2),
        dict(watershed='NorthFork',
            extent=[-122.22908020019533, 45.268121280142886, -121.74842834472658, 45.60539133629575],
            map_center=[-121.98875427246095, 45.43700828867391],
            map_zoom=11,
            outlet=[-122.03554486123724, 45.49455561832556],
            landuse=None,
            cs=150, erod=0.000001,
            csa=10, mcl=100,
	    surf_runoff=0.003, lateral_flow=0.004, baseflow=0.005, sediment=1000.0,
            gwstorage=100, bfcoeff=0.04, dscoeff=0.00, bfthreshold=1.001,
            mid_season_crop_coeff=0.95, p_coeff=0.95),
        dict(watershed='LittleSandy',
            extent=[-122.22908020019533, 45.268121280142886, -121.74842834472658, 45.60539133629575],
            map_center=[-121.98875427246095, 45.43700828867391],
            map_zoom=11,
            outlet=[-122.17147271631961, 45.415421615033246],
            landuse=None,
            cs=110, erod=0.000001,
            csa=10, mcl=100,
	    surf_runoff=0.003, lateral_flow=0.004, baseflow=0.005, sediment=1000.0,
            gwstorage=100, bfcoeff=0.04, dscoeff=0.00, bfthreshold=1.001,
            mid_season_crop_coeff=0.80, p_coeff=0.80)
    ]

    scenarios = [
               dict(wd='CurCond.202007.cl532.chn_cs{cs}',
                    landuse=None,
                    cli_mode='PRISMadj', clean=True, build_soils=True, build_landuse=True, build_climates=True),
               dict(wd='CurCond.202007.cl532_gridmet.chn_cs{cs}',
                    landuse=None,
                    cli_mode='observed', clean=True, build_soils=True, build_landuse=True, build_climates=True),
               dict(wd='SimFire_Eagle.202007.cl532.chn_cs{cs}',
                    landuse=None,
                    cfg='portland-simfire-eagle',
                    cli_mode='vanilla', clean=True, build_soils=True, build_landuse=True, build_climates=True),
               dict(wd='SimFire_Norse.202007.cl532.chn_cs{cs}',
                    landuse=None,
                    cfg='portland-simfire-norse',
                    cli_mode='vanilla', clean=True, build_soils=True, build_landuse=True, build_climates=True),
               dict(wd='PrescFireS.202007.chn_cs{cs}',
                    landuse=[(not_shrub_selector, 110), (shrub_selector, 122)],
                    cli_mode='vanilla', clean=True, build_soils=True, build_landuse=True, build_climates=True),
               dict(wd='LowSevS.202007.chn_cs{cs}',
                    landuse=[(not_shrub_selector, 106), (shrub_selector, 121)],
                    cli_mode='vanilla', clean=True, build_soils=True, build_landuse=True, build_climates=True),
               dict(wd='ModSevS.202007.chn_cs{cs}',
                    landuse=[(not_shrub_selector, 118), (shrub_selector, 120)],
                    cli_mode='vanilla', clean=True, build_soils=True, build_landuse=True, build_climates=True),
               dict(wd='HighSevS.202007.chn_cs{cs}',
                    landuse=[(not_shrub_selector, 105), (shrub_selector, 119)],
                    cli_mode='vanilla', clean=True, build_soils=True, build_landuse=True, build_climates=True),
                ]

    wc = sys.argv[-1]
    if '.py' in wc:
        wc = None

    projects = []
    for scenario in scenarios:
        for watershed in watersheds:
            projects.append(deepcopy(watershed))
            projects[-1]['cfg'] = scenario.get('cfg', 'lt')
            projects[-1]['landuse'] = scenario['landuse']
            projects[-1]['cli_mode'] = scenario.get('cli_mode', 'observed')
            projects[-1]['clean'] = scenario['clean']
            projects[-1]['build_soils'] = scenario['build_soils']
            projects[-1]['build_landuse'] = scenario['build_landuse']
            projects[-1]['build_climates'] = scenario['build_climates']
            projects[-1]['wd'] = 'portland_{watershed}_{scenario}'\
                                 .format(watershed=watershed['watershed'], scenario=scenario['wd'])\
                                 .format(cs=watershed['cs'])

    for proj in projects:
        config = proj['cfg']
        watershed_name = proj['watershed']
        wd = proj['wd']

        log_print(wd)
        if wc is not None:
            if not wc in wd:
                continue

        extent = proj['extent']
        map_center = proj['map_center']
        map_zoom = proj['map_zoom']
        outlet = proj['outlet']
        default_landuse = proj['landuse']
        cli_mode = proj['cli_mode']

        csa = proj['csa']
        mcl = proj['mcl']
        cs = proj['cs']
        erod = proj['erod']

        clean = proj['clean']
        build_soils = proj['build_soils']
        build_landuse = proj['build_landuse']
        build_climates = proj['build_climates']

        if clean:
            if _exists(wd):
                shutil.rmtree(wd)
            os.mkdir(wd)

            ron = Ron(wd, config + '.cfg')
            ron.name = wd
            ron.set_map(extent, map_center, zoom=map_zoom)
            ron.fetch_dem()

            log_print('building channels')
            topaz = Topaz.getInstance(wd)
            topaz.build_channels(csa=csa, mcl=mcl)
            topaz.set_outlet(*outlet)
            sleep(0.5)

            log_print('building subcatchments')
            topaz.build_subcatchments()

            log_print('abstracting watershed')
            watershed = Watershed.getInstance(wd)
            watershed.abstract_watershed()
            translator = watershed.translator_factory()
            topaz_ids = [top.split('_')[1] for top in translator.iter_sub_ids()]

        else:
            ron = Ron.getInstance(wd)
            topaz = Topaz.getInstance(wd)
            watershed = Watershed.getInstance(wd)

        landuse = Landuse.getInstance(wd)
        if build_landuse:
            landuse.mode = LanduseMode.Gridded
            landuse.build()
            landuse = Landuse.getInstance(wd)

            log_print('setting default landuses')

            if default_landuse is not None:
                log_print('setting default landuse')

                # tops = []
                for selector, dom in default_landuse:
                    _topaz_ids = selector(landuse, soils)
                    landuse.modify(_topaz_ids, dom)
                    # tops.extend(_topaz_ids)

        soils = Soils.getInstance(wd)
        if build_soils:
            log_print('building soils')
            soils.mode = SoilsMode.Gridded
            soils.build()

            log_print('adjusting restrictive layer ksat')
            ksat_mod = None

            _landslide = ShallowLandSlideSusceptibility()
            _bedrock = BullRunBedrock()

            if 'landslide' in wd:
                ksat_mod = 'l'
            elif 'groundwater' in wd:
                ksat_mod = 'g'
            else:
                ksat_mod = 'h'

            _domsoil_d = soils.domsoil_d
            _soils = soils.soils
            for topaz_id, ss in watershed._subs_summary.items():
                lng, lat = ss.centroid.lnglat

                if ksat_mod == 'l':
                    _landslide_pt = _landslide.get_bedrock(lng, lat)
                    ksat = _landslide_pt['ksat']
                    name = _landslide_pt['Unit_Name'].replace(' ', '_')

                elif ksat_mod == 'g':
                    _bedrock_pt = _bedrock.get_bedrock(lng, lat)
                    ksat = _bedrock_pt['ksat']
                    name = _bedrock_pt['Unit_Name'].replace(' ', '_')
                else:
                    _landslide_pt = _landslide.get_bedrock(lng, lat)
                    _landslide_pt_ksat = _landslide_pt['ksat']

                    _bedrock_pt = _bedrock.get_bedrock(lng, lat)
                    _bedrock_pt_ksat = _bedrock_pt['ksat']
                    ksat = _landslide_pt_ksat
                    name = _landslide_pt['Unit_Name'].replace(' ', '_')

                    if isfloat(_bedrock_pt_ksat):
                        ksat = _bedrock_pt_ksat
                        name = _bedrock_pt['Unit_Name'].replace(' ', '_')

                dom = _domsoil_d[str(topaz_id)]
                _soil = deepcopy(_soils[dom])

                _dom = '{dom}-{ksat_mod}_{bedrock_name}' \
                    .format(dom=dom, ksat_mod=ksat_mod, bedrock_name=name)
                if _dom not in _soils:
                    _soil_fn = '{dom}.sol'.format(dom=_dom)
                    src_soil_fn = _join(_soil.soils_dir, _soil.fname)
                    dst_soil_fn = _join(_soil.soils_dir, _soil_fn)
                    log_print(src_soil_fn, dst_soil_fn, ksat, _dom)
                    modify_ksat(src_soil_fn, dst_soil_fn, ksat)

                    _soil.fname = _soil_fn
                    _soils[_dom] = _soil

                _domsoil_d[str(topaz_id)] = _dom

            soils.lock()
            soils.domsoil_d = _domsoil_d
            soils.soils = _soils
            soils.dump_and_unlock()
            soils = Soils.getInstance(wd)

        climate = Climate.getInstance(wd)
        if build_climates:
            log_print('building climate')
            
            if cli_mode == 'observed':
                log_print('building observed')
                if 'linveh' in wd:
                    climate.climate_mode = ClimateMode.ObservedDb
                    climate.climate_spatialmode = ClimateSpatialMode.Multiple
                    climate.input_years = 21
    
                    climate.lock()
                    lng, lat = watershed.centroid
    
                    cli_path = lvdm.closest_cli(lng, lat)
                    _dir, cli_fn = _split(cli_path)
                    shutil.copyfile(cli_path, _join(climate.cli_dir, cli_fn))
                    climate.cli_fn = cli_fn
    
                    par_path = lvdm.par_path
                    _dir, par_fn = _split(par_path)
                    shutil.copyfile(par_path, _join(climate.cli_dir, par_fn))
                    climate.par_fn = par_fn
    
                    sub_par_fns = {}
                    sub_cli_fns = {}
                    for topaz_id, ss in watershed._subs_summary.items():
                        log_print(topaz_id)
                        lng, lat = ss.centroid.lnglat
    
                        cli_path = lvdm.closest_cli(lng, lat)
                        _dir, cli_fn = _split(cli_path)
                        run_cli_path = _join(climate.cli_dir, cli_fn)
                        if not _exists(run_cli_path):
                            shutil.copyfile(cli_path, run_cli_path)
                        sub_cli_fns[topaz_id] = cli_fn
                        sub_par_fns[topaz_id] = par_fn
    
                    climate.sub_par_fns = sub_par_fns
                    climate.sub_cli_fns = sub_cli_fns
                    climate.dump_and_unlock()
    
                elif 'daymet' in wd:
                    stations = climate.find_closest_stations()
                    climate.climatestation = stations[0]['id']
    
                    climate.climate_mode = ClimateMode.Observed
                    climate.climate_spatialmode = ClimateSpatialMode.Multiple
                    climate.set_observed_pars(start_year=1990, end_year=2017)
    
                    climate.build(verbose=1)
    
                    climate.lock()
    
                    cli_dir = climate.cli_dir
                    adj_cli_fn = _daymet_cli_adjust(cli_dir, climate.cli_fn, watershed_name)
                    climate.cli_fn = adj_cli_fn
    
                    for topaz_id in climate.sub_cli_fns:
                        adj_cli_fn = _daymet_cli_adjust(cli_dir, climate.sub_cli_fns[topaz_id], watershed_name)
                        climate.sub_cli_fns[topaz_id] = adj_cli_fn
    
                    climate.dump_and_unlock()
    
                elif 'gridmet' in wd:
                    log_print('building gridmet')
                    stations = climate.find_closest_stations()
                    climate.climatestation = stations[0]['id']
                        
                    climate.climate_mode = ClimateMode.GridMetPRISM
                    climate.climate_spatialmode = ClimateSpatialMode.Multiple
                    climate.set_observed_pars(start_year=1980, end_year=2019)
    
                    climate.build(verbose=1)
    
                    climate.lock()
    
                    cli_dir = climate.cli_dir
                    adj_cli_fn = _gridmet_cli_adjust(cli_dir, climate.cli_fn, watershed_name)
                    climate.cli_fn = adj_cli_fn
    
                    for topaz_id in climate.sub_cli_fns:
                        adj_cli_fn = _gridmet_cli_adjust(cli_dir, climate.sub_cli_fns[topaz_id], watershed_name)
                        climate.sub_cli_fns[topaz_id] = adj_cli_fn
    
                    climate.dump_and_unlock()

            elif cli_mode == 'PRISMadj':
                stations = climate.find_closest_stations()
                climate.climatestation = stations[0]['id']

                log_print('climate_station:', climate.climatestation)

                climate.climate_mode = ClimateMode.PRISM
                climate.climate_spatialmode = ClimateSpatialMode.Multiple
                climate.input_years = 100

                climate.build(verbose=1)

            elif cli_mode == 'vanilla':
                stations = climate.find_closest_stations()
                climate.climatestation = stations[0]['id']

                log_print('climate_station:', climate.climatestation)

                climate.climate_mode = ClimateMode.Vanilla
                climate.climate_spatialmode = ClimateSpatialMode.Single
                climate.input_years = 100

                climate.build(verbose=1)

        log_print('running wepp')
        wepp = Wepp.getInstance(wd)
        wepp.parse_inputs(proj)
		
        wepp.prep_hillslopes()
	
        log_print('running hillslopes')
        wepp.run_hillslopes()

        wepp = Wepp.getInstance(wd)
        wepp.prep_watershed(erodibility=erod, critical_shear=cs)
        wepp._prep_pmet(mid_season_crop_coeff=proj['mid_season_crop_coeff'], p_coeff=proj['p_coeff'])
        wepp.run_watershed()
        loss_report = wepp.report_loss()

        log_print('running wepppost')
        fn = _join(ron.export_dir, 'totalwatsed.csv')

        totwatsed = TotalWatSed(_join(ron.output_dir, 'totalwatsed.txt'),
                                wepp.baseflow_opts, wepp.phosphorus_opts)
        totwatsed.export(fn)
        assert _exists(fn)

        arc_export(wd)
