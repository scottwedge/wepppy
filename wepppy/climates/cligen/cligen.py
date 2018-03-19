import os
from os.path import join as _join
from os.path import exists as _exists

from datetime import datetime
import subprocess
import shutil
import math
from copy import deepcopy
import sqlite3

import pandas as pd

from wepppy.all_your_base import (
    isfloat,
    clamp,
    elevationquery,
    haversine
)
from wepppy.climates.metquery_client import *

_thisdir = os.path.dirname(__file__)
_db = _join(_thisdir, 'stations.db')
_stations_dir = _join(_thisdir, 'stations')
_bin_dir = _join(_thisdir, 'bin')


def df_to_prn(df, prn_fn, p_key, tmax_key, tmin_key):
    """
    creates a prn file containing daily timeseries data for input to
    cligen

    columns are formatted as
    {month} {day} {year} {p_in_tenthinches} {tmax} {tmin}
    """
    if 'mm' in p_key:
        df[p_key] /= 25.4

    df[p_key] *= 100.0
    df[p_key] = np.round(df[p_key])
    df[tmax_key] = np.round(c_to_f(df[tmax_key]))
    df[tmin_key] = np.round(c_to_f(df[tmin_key]))

    fp = open(prn_fn, 'w')
    mo, da, yr = 0, 0, 0
    for index, row in df.iterrows():

        if yr % 4 == 0 and mo == 12 and da == 30:
            da = 31
            fp.write("{0:<5}{1:<5}{2:<5}{3:<5}{4:<5}{5:<5}\r\n"
                     .format(mo, da, yr, p, tmax, tmin))

        mo, da, yr = int(index.month), int(index.day), int(index.year)
        p, tmax, tmin = int(row[p_key]), int(row[tmax_key]), int(row[tmin_key])

        fp.write("{0:<5}{1:<5}{2:<5}{3:<5}{4:<5}{5:<5}\r\n"
                 .format(mo, da, yr, p, tmax, tmin))
    fp.close()


def _row_formatter(values):
    """
    tasks a list of value and formats them as a string for .par files
    """
    s = []
    for v in values:
        if float(v) >= 100.0:
            s.append('%5.1f' % v)
        else:
            s.append('%5.2f' % v)
    return ' '.join(s).replace('0.', ' .')

days_in_mo = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])

class ClimateFile(object):
    def __init__(self, cli_fn):

        self.cli_fn = cli_fn
        with open(cli_fn) as fp:
            lines = fp.readlines()

        i = 0
        for i, L in enumerate(lines):
            if 'da mo year' in L:
                break

        header = lines[:i]
        colnames = [v.strip() for v in lines[i].split()]

        assert ' '.join(colnames) == \
               'da mo year prcp dur tp ip tmax tmin rad w-vl w-dir tdew'

        self.dtypes = [int, int, int, float, float, float, float,
                       float, float, float, float, float, float]
        self.data0line = i + 2
        self.lines = lines
        self.header = header
        self.colnames = colnames

    def replace_var(self, colname, dates, values):
        """
        supports the post processing of wepp files generated from
        daily observed or future data
        """
#        if colname in ['da', 'mo', 'year', 'prcp', 'tmax', 'tmin']:
#            raise ValueError('Cannot replace column "%s"' % colname)

        assert colname in self.colnames
        col_index = self.colnames.index(colname)

        d = dict(zip(dates, values))

        is_datetime = isinstance(dates[0], datetime)

        for i, L in enumerate(self.lines[self.data0line:]):
            row = [v.strip() for v in L.split()]
            if L.strip() == '':
                break

            assert len(row) == len(self.colnames), (len(row), row, len(self.colnames), self.colnames)

            day, month, year = [int(v) for v in row[:3]]

            if is_datetime:
                date = datetime(year, month, day)
            else:
                date = int(year), int(month), int(day)

            value = d.get(date, None)
            if value is None:
                continue

            row[col_index] = str(value)

            for j, (c, v) in enumerate(zip(self.colnames, row)):
                if c in ['da', 'mo', 'year']:
                    row[j] = '%i' % int(v)
                elif c in ['rad', 'w-dir']:
                    row[j] = '%.f' % float(v)
                else:
                    row[j] = '%.1f' % float(v)

            row = '{0:>3}{1:>3}{2:>5}{3:>6}{4:>6}{5:>5}{6:>7}'\
                  '{7:>6}{8:>6}{9:>5}{10:>5}{11:>6}{12:>6}\n'\
                  .format(*row)

            self.lines[self.data0line + i] = row

    def as_dataframe(self):
        colnames = self.colnames
        dtypes = self.dtypes
        d = {}
        for name in colnames:
            d[name] = []

        for i, L in enumerate(self.lines[self.data0line:]):
            row = [v.strip() for v in L.split()]
            if L.strip() == '':
                break

            assert len(row) == len(self.colnames), (len(row), len(self.colnames))

            for dtype, name, v in zip(dtypes, colnames, row):
                d[name].append(dtype(v))

        return pd.DataFrame(data=d)

    def header_ppts(self):
        ppts = []
        for ppt in self.lines[12].split():
            try:
                ppts.append(float(ppt))
            except ValueError:
                ppts.append(float('nan'))

        assert len(ppts) == 12
        ppts = np.array(ppts)
        ppts *= 0.0393701
        ppts /= days_in_mo
        return ppts

    def count_wetdays(self):
        df = self.as_dataframe()
        nyears = len(set(df.year))

        df['wet'] = df.prcp > 0.0
        tbl = pd.pivot_table(df, values='wet', index=['mo'], aggfunc=np.sum)
        return tbl.wet/float(nyears)

    def calc_monthlies(self):
        df = self.as_dataframe()
        nyears = len(set(df.year))

        prcps = np.zeros((12,))
        tmaxs = np.zeros((12,))
        tmins = np.zeros((12,))

        for i, row in df.iterrows():
            prcps[int(row.mo) - 1] += row.prcp
            tmaxs[int(row.mo) - 1] += row.tmax
            tmins[int(row.mo) - 1] += row.tmin

        prcps /= nyears * days_in_mo
        prcps *= 0.0393701  # convert to inches/month

        tmaxs /= nyears * days_in_mo
        tmaxs = c_to_f(tmaxs)

        tmins /= nyears * days_in_mo
        tmins = c_to_f(tmins)

        return {
            "ppts": list(prcps),
            "tmaxs": list(tmaxs),
            "tmins": list(tmins)
        }

    def write(self, fn):
        with open(fn, 'w') as fp:
            fp.write(''.join(self.lines))
            
    @property
    def contents(self):
        return ''.join(self.lines)


class Station:
    def __init__(self, par_fn):
        with open(par_fn) as fp:
            lines = fp.readlines()

        assert 'MEAN P' in lines[3]
        assert 'S DEV P' in lines[4]
        assert 'TMAX' in lines[8]
        assert 'TMIN' in lines[9]
        assert 'P(W/W)' in lines[6]
        assert 'P(W/D)' in lines[7]

        self.ppts = np.array([float(lines[3][-73:][i * 6:i * 6 + 6]) for i in range(12)])
        self.pstds = np.array([float(lines[4][-73:][i * 6:i * 6 + 6]) for i in range(12)])
        self.pwws = np.array([float(lines[6][-73:][i * 6:i * 6 + 6]) for i in range(12)])
        self.pwds = np.array([float(lines[7][-73:][i * 6:i * 6 + 6]) for i in range(12)])
        self.tmaxs = np.array([float(lines[8][-73:][i * 6:i * 6 + 6]) for i in range(12)])
        self.tmins = np.array([float(lines[9][-73:][i * 6:i * 6 + 6]) for i in range(12)])

        assert len(self.ppts) == 12
        assert len(self.pstds) == 12
        assert len(self.pwws) == 12
        assert len(self.pwds) == 12
        assert len(self.tmaxs) == 12
        assert len(self.tmins) == 12

        mdays = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
        self.nwds = mdays * (self.pwds / (1.0 - self.pwws + self.pwds))

        self.lines = lines


    def localize(self, lng, lat,
                 p_mean='prism',
                 p_std='daymet',
                 p_skew='daymet',
                 p_ww='daymet',
                 p_wd='daymet',
                 tmax='prism',
                 tmin='prism',
                 dewpoint='prism',
                 solrad='daymet'):

        new = deepcopy(self)

        if p_mean == 'prism':
            ppts = get_prism_monthly_ppt(lng, lat, units='daily inch')
            new.lines[3] = ' MEAN P  ' + _row_formatter(ppts) + '\r\n'

        elif p_mean == 'daymet':
            ppts = get_daymet_prcp_mean(lng, lat, units='daily inch')
            new.lines[3] = ' MEAN P  ' + _row_formatter(ppts) + '\r\n'

        if p_std == 'daymet':
            p_stds = get_daymet_prcp_std(lng, lat, units='inch')
            new.lines[4] = ' S DEV P ' + _row_formatter(p_stds) + '\r\n'

        if p_skew == 'daymet':
            p_skew = get_daymet_prcp_skew(lng, lat, units='inch')
            new.lines[5] = ' SKEW P  ' + _row_formatter(p_skew) + '\r\n'

        if p_ww == 'daymet':
            p_wws = get_daymet_prcp_pww(lng, lat)
            p_wws = [clamp(v, 0.01, 0.99) for v in p_wws]
            new.lines[6] = ' P(W/W)  ' + _row_formatter(p_wws) + '\r\n'
        elif isfloat(p_ww):
            p_wws = self.pwws * float(p_ww)
            p_wws = [clamp(v, 0.01, 0.99) for v in p_wws]
            new.lines[6] = ' P(W/W)  ' + _row_formatter(p_wws) + '\r\n'

        if p_wd == 'daymet':
            p_wds = get_daymet_prcp_pwd(lng, lat)
            p_wds = [clamp(v, 0.01, 0.99) for v in p_wds]
            new.lines[7] = ' P(W/D)  ' + _row_formatter(p_wds) + '\r\n'
        elif isfloat(p_wd):
            p_wds = self.pwds * float(p_wd)
            p_wds = [clamp(v, 0.01, 0.99) for v in p_wds]
            new.lines[7] = ' P(W/D)  ' + _row_formatter(p_wds) + '\r\n'

        if tmax == 'prism':
            tmaxs = get_prism_monthly_tmax(lng, lat, units='f')
            new.lines[8] = ' TMAX AV ' + _row_formatter(tmaxs) + '\r\n'

        if tmin == 'prism':
            tmins = get_prism_monthly_tmin(lng, lat, units='f')
            new.lines[9] = ' TMIN AV ' + _row_formatter(tmins) + '\r\n'

        if solrad == 'daymet':
            slrds = get_daymet_srld_mean(lng, lat)
            new.lines[12] = ' SOL.RAD ' + _row_formatter(slrds) + '\r\n'

        if dewpoint == 'prism':
            tdmeans = get_prism_monthly_tdmean(lng, lat, units='f')
            new.lines[15] = ' DEW PT  ' + _row_formatter(tdmeans) + '\r\n'

        return new

    def write(self, fn):
        with open(fn, 'w') as fp:
            fp.write(''.join(self.lines))


class StationMeta:
    def __init__(self, state, desc, par, latitude, longitude, years, _type,
                 elevation, tp5, tp6, _distance=None):
        self.state = state
        self.par = par
        self.latitude = latitude
        self.longitude = longitude
        self.years = years
        self.type = _type
        self.elevation = elevation
        self.tp5 = tp5
        self.tp6 = tp6
        self.distance = None
        self.rank = None

        self.id = ''.join([v for v in par if v in '0123456789'])
        assert len(self.id) == 6

        self.desc = desc.split(str(self.id))[0].strip()

        self.parpath = _join(_thisdir, "stations", par)
        assert _exists(self.parpath)

    def get_station(self):
        return Station(self.parpath)

    def calculate_distance(self, location):
        self.distance = haversine(location, (self.longitude, self.latitude))

    def as_dict(self, include_monthlies=False):
    
        d = {
            "state": self.state,
            "desc": self.desc,
            "par": self.par,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "years": self.years,
            "type": self.type,
            "elevation": self.elevation,
            "tp5": self.tp5,
            "tp6": self.tp6,
            "distance_to_query_location": self.distance,
            "rank_based_on_query_location": self.rank,
            "id": int(self.id)
        }
        
        if include_monthlies:
            station = self.get_station()
            d["monthlies"] = { 
                "ppts": list(station.ppts),
                "tmaxs": list(station.tmaxs),
                "tmins": list(station.tmins)
            }

        return d
            
    def __repr__(self):
        return "%s(%r)" % (self.__class__, self.__dict__)


class CligenStationsManager:
    def __init__(self):

        # connect to sqlite3 db
        global _db
        conn = sqlite3.connect(_db)
        c = conn.cursor()

        # load station meta data
        self.stations = []
        c.execute("SELECT * FROM stations")
        for row in c:
            self.stations.append(StationMeta(*row))

    def order_by_distance_to_location(self, location):
        """
        location in longitude, latitude
        """
        for station in self.stations:
            station.calculate_distance(location)

        self.stations = \
            sorted(self.stations, key=lambda s: s.distance)

    def get_closest_station(self, location):
        self.order_by_distance_to_location(location)
        return self.stations[0]

    def get_closest_stations(self, location, num_stations):
        self.order_by_distance_to_location(location)
        return self.stations[:num_stations]

    def get_station_fromid(self, _id):
        for station in self.stations:
            if str(_id) in str(station.par):
                return station
        return None

    def get_station_heuristic_search(self, location, pool=10):
        return self.get_stations_heuristic_search(location, pool=pool)[0]

    def get_stations_heuristic_search(self, location, pool=10):

        stations = self.get_closest_stations(location, pool)

        lat_ranks = [(i, abs(s.latitude - location[1]))
                     for i, s in enumerate(stations)]
        lat_ranks = sorted(lat_ranks, key=lambda x: x[1])

        elev = elevationquery(*location)
        stations_elevs = np.array([elevationquery(s.longitude, s.latitude)
                                   for s in stations])
        stations_elevs -= elev
        stations_elevs = np.abs(stations_elevs)
        elev_ranks = [(i, err) for i, err in enumerate(stations_elevs)]
        elev_ranks = sorted(elev_ranks, key=lambda x: x[1])

        ppts = get_prism_monthly_ppt(*location, units='daily inch')

        ppt_ranks = np.array([math.sqrt(np.sum((s.get_station().ppts - ppts)**2.0))
                              for s in stations])
        ppt_ranks = [(i, err) for i, err in enumerate(ppt_ranks)]
        ppt_ranks = sorted(ppt_ranks, key=lambda x: x[1])

        s_ranks = list(range(pool))
        for ranks in [lat_ranks, elev_ranks, ppt_ranks]:

            for score, (i, err) in enumerate(ranks):
                s_ranks[i] += score

        s_ranks = [(i, err) for i, err in enumerate(s_ranks)]
        s_ranks = sorted(s_ranks, key=lambda x: x[1])

        _stations = []
        for i, rank in s_ranks:
            _stations.append(stations[i])
            _stations[-1].rank = rank

        return _stations


class Cligen:
    def __init__(self, station, wd='./', cliver="4.3"):
        assert _exists(wd), 'Working dir does not exist'
        self.wd = wd

        assert isinstance(station, StationMeta), "station is not a StationMeta object"
        self.station = station

        self.cliver = cliver

        self.cligen52 = _join(_thisdir, "bin", "cligen52")
        self.cligen43 = _join(_thisdir, "bin", "cligen43")

        assert _exists(self.cligen52), "Cannot find cligen52 executable"
        assert _exists(self.cligen52), "Cannot find cligen43 executable"

    def _make_clinp(self, years, cli_fname, par):
        """
        makes an input file that is passed as stdin to cligen
        """
        clinp = _join(self.wd, "clinp.txt")
        fid = open(clinp, "w")

        if self.cliver == "5.2":
            fid.write("5\n1\n{years}\n{cli_fname}\nn\n\n"
                      .format(years=years, cli_fname=cli_fname))
        else:
            fid.write("\n{par}\nn\n5\n1\n{years}\n{cli_fname}\nn\n\n"
                      .format(par=par, years=years, cli_fname=cli_fname))

        fid.close()

        assert _exists(clinp)

    def run_multiple_year(self, years, cli_fname='wepp.cli',
                          localization=None, verbose=True):

        if verbose:
            print("running multiple year")

        assert cli_fname.endswith('.cli')

        station_meta = self.station

        if localization is None:
            # no prism adjustment is specified
            # just copy the par into the working directory
            par_fn = _join(self.wd, station_meta.par)
            shutil.copyfile(station_meta.parpath, par_fn)
        else:
            # adjust based on lng, lat
            lng, lat = localization
            assert lng >= -125.0208333
            assert lng <= -66.4791667
            assert lat >= 24.0625000
            assert lat <= 49.9375000

            station = station_meta.get_station()
            new_station = station.localize(lng, lat)

            par_fn = '%s.%s.par' % (station_meta.par[:-4], cli_fname[:-4])
            par_fn = _join(self.wd, par_fn)
            new_station.write(par_fn)

        assert _exists(par_fn)
        _, par = os.path.split(par_fn)

        self._make_clinp(years, cli_fname, par)

        if self.cliver == "5.2":
            cmd = [self.cligen52, "-i%s" % par]
        else:
            cmd = [self.cligen43]

        # remember current directory
        curdir = os.getcwd()

        # change to working directory
        os.chdir(self.wd)

        # delete cli file if it exists
        if _exists(cli_fname):
            os.remove(cli_fname)

        _clinp = open("clinp.txt")
        _log = open("cligen.log", "w")
        p = subprocess.Popen(cmd, stdin=_clinp, stdout=_log, stderr=_log)
        p.wait()
        _clinp.close()
        _log.close()

        assert _exists(cli_fname)

        # change to back to original directory
        os.chdir(curdir)


if __name__ == "__main__":
    stationManager = CligenStationsManager()
       
    sm = stationManager.get_station_fromid(48758)
    print(sm.par)
