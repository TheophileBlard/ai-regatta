import numpy as np
import requests
import xarray as xr

import datetime
import os


class WeatherGrabber:
    UTC_RANGE = np.arange(0, 23, 3)  # every three hours
    GRIB_URL = "http://zezo.org/grib/gribv1/archived/"

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir

    def get_weather(self, date: datetime.datetime):
        current_utc = self.UTC_RANGE[self.UTC_RANGE <= date.hour].max()
        grib_file = self._get_grib_file(date.date(), current_utc)
        ds = xr.open_dataset(grib_file, engine="cfgrib")
        ds["longitude"] = ds.longitude - 180
        ds["u_norm"] = ds.u10 / (ds.u10 ** 2 + ds.v10 ** 2) ** 0.5
        ds["v_norm"] = ds.v10 / (ds.u10 ** 2 + ds.v10 ** 2) ** 0.5
        ds["wind_speed"] = (ds.u10 ** 2 + ds.v10 ** 2) ** 0.5
        return ds

    def _get_grib_file(self, date: datetime.date, utc: int):
        if date.year < 2017:
            raise ValueError(f"Cannot get grib data prior to 2017: {date}")
        if date >= datetime.date.today():
            raise ValueError(f"Given date is not archived yet: {date}")
        if utc not in self.UTC_RANGE:
            raise ValueError(f"Invalid UTC tag: {utc}")
        utc_tag = str(utc).rjust(3, "0")  # add leading 0s
        filename = f'{date.strftime("%Y%m%d")}_{utc_tag}.grib'
        if date.year < datetime.date.today().year:
            filename = f"{date.year}/{filename}"
        # 1. check if local data exist
        localpath = os.path.join(self.cache_dir, filename)
        if os.path.exists(localpath):
            # print(f"Using cached data: {localpath}")
            return localpath
        # 2. otherwise download it
        url = os.path.join(self.GRIB_URL, filename)
        #print(f"Downloading data: {url}")
        response = requests.get(url, stream=True)
        if response.status_code != 200:
            raise Exception(f"Failed to download {url}")
        os.makedirs(os.path.dirname(localpath), exist_ok=True)
        with open(localpath, "wb") as f:
            for data in response.iter_content(): #tqdm(response.iter_content()):
                f.write(data)
        return localpath
