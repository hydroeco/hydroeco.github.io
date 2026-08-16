#!/usr/bin/env python3
"""Update Rancho Venada Dendra weather data and dashboard images."""

import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import dendra_api_client as dendra


DATA_DIR = Path.home() / 'hydroeco.github.io' / 'rancho_venada'
RVWS_FILE = DATA_DIR / 'rvws.csv'

dendra.authenticate()

# pull weather
print('Pulling weather data')
current_date = datetime.datetime.now()
current_water_year = current_date.year + 1*int((current_date.month>=10)&(current_date.month<=12))
wystart = str(current_water_year-1) + '-10'
rvws = pd.read_csv(RVWS_FILE, index_col=0)
try:
    rvws.index = pd.to_datetime(rvws.index,format='%m/%d/%y %H:%M')
except: 
    rvws.index = pd.to_datetime(rvws.index,format='%Y-%m-%d %H:%M:%S')

from_time = pd.to_datetime(rvws.index[-1]) - pd.to_timedelta(4,unit='D')
from_time = from_time.isoformat()
from_time = from_time.split('.')[0]
station = dendra.list_datastreams_by_station_id('5ca6ac9196f0c41fa0f7e7d5')
names = [
  'Rainfall',
  'Air Temp Avg',
  'Barometric Pressure',
  'Relative Humidity Max','Solar Radiation Avg','Wind Speed Avg','Wind Direction']
dsids = []
dfs = []
for item in names:
    dsid = [stream['_id'] for stream in station if item==stream['name'] ][0]
    dsids.append(dsid)
    temp = dendra.get_datapoints_from_id_list([dsid], begins_at=from_time)
    temp.timestamp_local = pd.to_datetime(temp.timestamp_local)
    temp = temp.set_index('timestamp_local')
    temp = temp.drop('timestamp_utc',axis=1)
    dfs.append(temp)

df = pd.concat(dfs,axis=1)
df = pd.concat([df,rvws])
df = df.loc[~df.index.duplicated(keep='first')]
df = df.sort_index()
df.to_csv(RVWS_FILE)


rvws = pd.read_csv(RVWS_FILE, index_col=0, parse_dates=True)
tempname = 'RanchoVenadaWs_Air_Temp_Avg'
relname = 'RanchoVenadaWs_Relative_Humidity_Max'
airtemp_wssr = rvws[tempname]
relH_wssr = rvws[relname]
SVP_wssr = 610.7*10**(7.5*airtemp_wssr/(237.3+airtemp_wssr))#[Pa]
vpd_wssr = (((100-relH_wssr)/100)*SVP_wssr)/1000 #KPa
vpd_wssr = pd.DataFrame({'vpd':vpd_wssr.values}, index=vpd_wssr.index).sort_index().resample('1H').mean()
freq = '1H'

newnames = {'RanchoVenadaWs_Air_Temp_Avg':'Temp (F)', 
            'RanchoVenadaWs_Rainfall':'Precip (in)',
       'RanchoVenadaWs_Relative_Humidity_Max':'Rel humidity ( )',
       'RanchoVenadaWs_Barometric_Pressure':'Pressure (in Hg)',
       'RanchoVenadaWs_Wind_Speed_Avg':'Wind (mph)',
       'RanchoVenadaWs_Solar_Radiation_Avg':'Rad. (w/m2)'}
rvws = rvws[list(newnames)]
newcols = [newnames[item] for item in rvws.columns]
rvws.columns = newcols
rvws['Temp (F)'] = rvws['Temp (F)']*9/5. + 32.
rvws['Precip (in)'] = rvws['Precip (in)']*0.0393701
rvws['Pressure (in Hg)'] = rvws['Pressure (in Hg)']*0.02953
rvws['Wind (mph)'] = rvws['Wind (mph)']*2.23694
rvws['Rel humidity ( )'] = rvws['Rel humidity ( )']/100.0
rvws = rvws.resample(freq).agg({'Temp (F)': np.mean,
                                'Precip (in)': np.sum,
                                'Pressure (in Hg)': np.mean,
                                'Wind (mph)':np.mean,
                                'Rel humidity ( )': np.mean, 
                                'Rad. (w/m2)':np.mean})


rvws['wy'] = [item.year if item.month>=1 and item.month<10 else item.year+1 for item in rvws.index]
rvws['Precip (in)'] = rvws.groupby('wy').apply(lambda item: item['Precip (in)'].cumsum()).values
rvws = rvws.loc[rvws.wy==rvws.wy.max()]
rvws = rvws[['Wind (mph)', 'Precip (in)', 'Temp (F)', 'Rel humidity ( )']]


  
f, axs = plt.subplots(2,2,sharex=True,figsize=(12,5))
ax = axs[0][0]
ax.plot(rvws['Precip (in)'],lw=3)
ax.set_ylabel('Cumulative precip (in)')
ax.set_ylim([0, int(rvws['Precip (in)'].max())+1])
ax.yaxis.grid(True,ls='-')
ax.xaxis.grid(True,which='minor',ls=':')
ax.xaxis.grid(True,which='major',ls='-')

ax = axs[0][1]
ax.plot(rvws['Wind (mph)'],c='tab:green',lw=2)
ax.set_ylabel('Windspeed (mph)')
ax.yaxis.grid(True,ls='-')
ax.xaxis.grid(True,which='minor',ls=':')
ax.xaxis.grid(True,which='major',ls='-')

ax = axs[1][0]
ax.plot(rvws['Temp (F)'],c='tab:red',lw=2)
ax.set_ylabel('Temp (F)')
ax.yaxis.grid(True,ls='-')
ax.xaxis.grid(True,which='minor',ls=':')
ax.xaxis.grid(True,which='major',ls='-')

ax = axs[1][1]
ax.plot(100*rvws['Rel humidity ( )'],label='Humidity (%)',c='tab:orange',lw=2)
ax.set_ylabel('Humidity (%)')
ax.yaxis.grid(True,ls='-')
ax.xaxis.grid(True,which='minor',ls=':')
ax.xaxis.grid(True,which='major',ls='-')

title = 'Current as of: ' + pd.to_datetime(rvws.index.values[-1]).strftime("%Y-%m-%d %H:%M")
ax.xaxis.set_minor_locator(mdates.DayLocator(interval=1))
ax.xaxis.set_major_locator(mdates.DayLocator(interval=7))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
f.autofmt_xdate()
f.suptitle('Water year weather',fontsize=16)

f.tight_layout(rect=[0, 0.03, 1, 0.95])
f.savefig(DATA_DIR / 'weather_wy.png', dpi=300)
plt.close(f)

f, axs = plt.subplots(2,2,sharex=True,figsize=(12,5))
ax = axs[0][0]
idx1 = rvws.index[-1]-pd.to_timedelta(2,unit='D')
idx2 = rvws.index[-1]
rvws = rvws.loc[idx1:idx2]
ax.plot(rvws['Precip (in)'],lw=3)
ax.set_ylabel('Cumulative precip (in)')
ax.set_ylim([rvws['Precip (in)'].min()-0.5, int(rvws['Precip (in)'].max())+1])
ax.yaxis.grid(True,ls='-')
ax.xaxis.grid(True,which='minor',ls=':')
ax.xaxis.grid(True,which='major',ls='-')

ax = axs[0][1]
ax.plot(rvws['Wind (mph)'],c='tab:green',lw=2)
ax.set_ylabel('Windspeed (mph)')
ax.yaxis.grid(True,ls='-')
ax.xaxis.grid(True,which='minor',ls=':')
ax.xaxis.grid(True,which='major',ls='-')

ax = axs[1][0]
ax.plot(rvws['Temp (F)'],c='tab:red',lw=2)
ax.set_ylabel('Temp (F)')
ax.yaxis.grid(True,ls='-')
ax.xaxis.grid(True,which='minor',ls=':')
ax.xaxis.grid(True,which='major',ls='-')

ax = axs[1][1]
ax.plot(100*rvws['Rel humidity ( )'],label='Humidity (%)',c='tab:orange',lw=2)
ax.set_ylabel('Humidity (%)')
ax.yaxis.grid(True,ls='-')
ax.xaxis.grid(True,which='minor',ls=':')
ax.xaxis.grid(True,which='major',ls='-')


title = 'Current as of: ' + pd.to_datetime(rvws.index.values[-1]).strftime("%Y-%m-%d %H:%M")
ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
f.autofmt_xdate()
f.suptitle('Most recent 48 hours',fontsize=16)

f.tight_layout(rect=[0, 0.03, 1, 0.95])

f.savefig(DATA_DIR / 'weather_48.png', dpi=300)
plt.close(f)


filepath = DATA_DIR / 'wx_dash.html'
seasontotal = rvws['Precip (in)'].values[-1]
idx = rvws.index[-1] 
idxstr = idx.strftime("%m/%d/%Y, %H:%M:%S")
idxrewind = rvws.index[np.where(rvws.index >= idx - pd.to_timedelta(1,unit='day'))[0][0]]

seasontotalmm = seasontotal*1/0.0393701
last24 = rvws['Precip (in)'].loc[idx] - rvws['Precip (in)'].loc[idxrewind]
last24mm = last24*1/0.0393701
currenttemp = rvws['Temp (F)'].values[-1]
currenttempC = (currenttemp-32.0)*5/9 


titletext = '<h1 align="center">Rancho Venada Weather Station Dashboard</h1>'
toadd = "<h2 align='center'>Return to <a target='_blank' href='./wells_piezos_dash.html'>borings/piezo dashboard</a> or <a target='_blank' href='./mymap.html'>map</a>.</h2>"
titletext = titletext + toadd
toadd = 'Current as of %s'%idxstr
titletext = titletext + toadd 
toadd = '<br>Download <a href="https://hydroeco.github.io/rancho_venada/rvws.csv" download>weather</a> or <a href="https://hydroeco.github.io/rancho_venada/sap.csv" download>sapflow</a>'
titletext = titletext + toadd
toadd = '<br><a target="_blank" href="https://ambientweather.net/dashboard/9e909d58d0c963aadbfcdcaabf8f3975">Link</a> to ambient weather station'
titletext = titletext + toadd
titletext = titletext + "<h2 align='left'> Current water year precip: %.1f in (%.2f mm)</h2>"%(seasontotal,seasontotalmm)
titletext = titletext + "<h2 align='left'> Precip last 24 hours: %.1f in (%.2f mm)</h2>"%(last24,last24mm)
titletext = titletext + "<h2 align='left'> Current temperature: %.1f F (%.1f C)</h2>"%(currenttemp ,currenttempC)

towrite = '''
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* {
box-sizing: border-box;
}

body {
margin: 0;
font-family: Arial;
}

/* The grid: Four equal columns that floats next to each other */
.column {
float: left;
width: 25%;
padding: 10px;
}

/* Style the images inside the grid */
.column img {
opacity: 0.8; 
cursor: pointer; 
}

.column img:hover {
opacity: 1;
}

/* Clear floats after the columns */
.row:after {
content: "";
display: table;
clear: both;
}

/* The expanding image container */
.container {
position: relative;
display: none;
}

/* Expanding image text */
#imgtext {
position: absolute;
bottom: 15px;
left: 15px;
color: white;
font-size: 20px;
}

/* Closable button inside the expanded image */
.closebtn {
position: absolute;
top: 10px;
right: 15px;
color: white;
font-size: 35px;
cursor: pointer;
}
</style>
</head>
<body>

'''
towrite = towrite + titletext


toadd = '''  
<!-- The columns -->
<div class="row">
  <div class="column">
    <br>Water year</br>
    <img src="./weather_wy.png" alt="WY" style="width:100%" onclick="myFunction(this);">
  </div>
  <div class="column">
      <br>Most recent 48 hours</br>
    <img src="./weather_48.png" alt="48" style="width:100%" onclick="myFunction(this);">
  </div>
</div>

<div class="container">
  <span onclick="this.parentElement.style.display='none'" class="closebtn">&times;</span>
  <img id="expandedImg" style="width:90%">
  <div id="imgtext"></div>
</div>

<script>
function myFunction(imgs) {
  var expandImg = document.getElementById("expandedImg");
  var imgText = document.getElementById("imgtext");
  expandImg.src = imgs.src;
  imgText.innerHTML = imgs.alt;
  expandImg.parentElement.style.display = "block";
}
</script>

</body>
</html>

'''
towrite = towrite + toadd

with filepath.open('w') as write_file:
    write_file.write(towrite + "\n")
