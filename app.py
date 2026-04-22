from flask import Flask, jsonify, render_template_string
import socket
import pandas as pd
from datetime import datetime
import os
from pathlib import Path
import subprocess

app = Flask(__name__)

NUT_HOST = "172.21.0.1"
NUT_PORT = 3493
UPS_NAME = "cyberpower"

if "__file__" in globals():
    BASE_DIR = Path(__file__).resolve().parent
else:
    BASE_DIR = Path(os.getcwd())

def nut_command(cmd):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect((NUT_HOST, NUT_PORT))
        s.sendall((cmd + "\n").encode())
        response = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            response += chunk
            if b"END LIST" in response or b"ERR" in response:
                break
        return response.decode()

def get_ups_vars():
    raw = nut_command(f"LIST VAR {UPS_NAME}")
    data = {}
    for line in raw.splitlines():
        if line.startswith("VAR"):
            parts = line.split(" ", 3)
            if len(parts) == 4:
                key = parts[2]
                value = parts[3].strip('"')
                data[key] = value
    return data

@app.route("/ups")
def ups():
    try:
        vars = get_ups_vars()
        return jsonify({
            "status": vars.get("ups.status", "unknown"),
            "battery_charge": vars.get("battery.charge"),
            "battery_runtime": vars.get("battery.runtime"),
            "battery_runtime_low": vars.get("battery.runtime.low"),
            "load": vars.get("ups.load"),
            "input_voltage": vars.get("input.voltage"),
            "output_voltage": vars.get("output.voltage"),
            "nominal_power": vars.get("ups.realpower.nominal"),
            "model": vars.get("ups.model"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/cpu_widget")
def cpu_widget():
    df = pd.read_csv(BASE_DIR / 'metrics.csv')
    df['date'] = pd.to_datetime(df['date'])
    today = pd.Timestamp.now()
    chart_start = today - pd.Timedelta(days=1)

    cpu_data = (
        df.loc[
            (df['date'] >= chart_start) &
            (df['Tdie'].notna()) &
            (df['Tdie'] > 0),
            ['date', 'cpu_avg_10s', 'Tdie']
        ]
        .copy()
        .sort_values('date')
    )

    cpu_data['cpu_usage_3_avg'] = (
        cpu_data['cpu_avg_10s']
        .rolling(window=3)
        .max()
        .round(1)
    )

    cpu_data['Tdie_3_avg'] = (
        cpu_data['Tdie']
        .rolling(window=3)
        .max()
        .round(1)
    )

    cpu_data = cpu_data.dropna(subset=['Tdie_3_avg'])

    cpu_data = cpu_data.assign(
        date=cpu_data['date'].dt.strftime('%d %H:%M')
    ).rename(columns={
        'cpu_avg_10s': 'cpu_usage'
    }).to_dict('records')
            
    cpu_df = (
        df.loc[
            (df['Tdie'].notna()) &
            (df['Tdie'] > 0),
            ['date', 'cpu_avg_10s', 'Tdie']
        ]
        .copy()
        .sort_values('date')
    )

    labels = [d['date'] for d in cpu_data][::3]
    cpu_usage_trend = [d['cpu_usage_3_avg'] for d in cpu_data][::3]
    tdie_trend = [d['Tdie_3_avg'] for d in cpu_data][::3]

    # Extract the maximum CPU usage from the 'cpu_usage' column
    max_cpu_usage = cpu_df['cpu_avg_10s'].max()
    percentile_95_cpu_usage = round(cpu_df['cpu_avg_10s'].quantile(0.95),1)
    max_tdie = cpu_df['Tdie'].max()
    min_tdie = cpu_df['Tdie'].min()
    percentile_95_tdie = round(cpu_df['Tdie'].quantile(0.95),1)
    tdie_min_above_70 = sum(1 for temp in cpu_df['Tdie'] if temp > 70)

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500&display=swap" rel="stylesheet">
<style>
  html, body {{ margin: 0; height: fit-content; background-color: hsl(232, 23%, 18%) !important; font-family: 'Inter', sans-serif; font-size: 13px; }}
  .primary {{ color: #ffffff; }}
  .row {{ margin: 1px 0; font-size: 12px; }}
  p {{ margin: 3px 0; }}
  canvas {{ width: 100% !important; }}
  * {{
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }}
</style>
</head>
<body>  
  <div style="background: rgba(37,40,60,1); border: 1px solid hsl(232, 23%, 22%); box-shadow: 0px 3px 0px 0px hsl(232, 23%, 18%); border-radius: 8px; padding: 16px 16px;">
  <p><span style="color: #a0b4d0">Max CPU usage (5s avg) (last 7d): </span><span style="font-weight:500; color: #A070FF">{max_cpu_usage} %</span><span style="color: #a0b4d0"> // </span><span style="font-weight:500; color: #A070FF">{percentile_95_cpu_usage}% (95%)</span></p>
  <p><span style="color: #a0b4d0">Max Tdie (last 7d): </span><span style="font-weight:500; color: #F46060">{max_tdie} ºC</span><span style="color: #a0b4d0"> // </span><span style="font-weight:500; color: #F46060">{percentile_95_tdie}ºC (95%)</span></p>
  <p><span style="color: #a0b4d0">Min Tdie (last 7d): </span><span style="font-weight:500; color: #60F4A2">{min_tdie} ºC</span></p>
  <p><span style="color: #a0b4d0">Tdie Above 70ºC (last 7d): </span><span style="font-weight:500; color: #F46060">{tdie_min_above_70} min</span></p>
  <div style="margin-top: 10px;">
  <p class="hl" style="margin-top:8px; font-weight:500; margin:4px 0 0; color:#ffffff">Trends - Last 24h</p>
    <div style="position: relative; height: 190px; width: 100%; margin-top: 5px;">
      <canvas id="chart"></canvas>
    </div>
  </div>
  </div>
</body>
<script>
  window.addEventListener('message', function(e) {{
    if (e.data && e.data.glanceTheme) {{
      var t = e.data.glanceTheme;
      var r = document.documentElement;
      // Actualizamos las variables raíz para que el fondo y colores cambien dinámicamente
      if (t.bgh) r.style.setProperty('--bgh', t.bgh);
      if (t.bgs) r.style.setProperty('--bgs', t.bgs);
      if (t.bgl) r.style.setProperty('--bgl', t.bgl);
      if (t.positive) r.style.setProperty('--color-positive', t.positive);
      if (t.negative) r.style.setProperty('--color-negative', t.negative);
      if (t.primary) r.style.setProperty('--color-primary', t.primary);
    }}
  }});
Chart.defaults.font.family = 'Inter, sans-serif';
  Chart.defaults.font.size = 12;
  new Chart(document.getElementById('chart'), {{
    type: 'line',
    data: {{
      labels: {labels},
      datasets: [
        {{ label: 'CPU (%)', data: {cpu_usage_trend}, pointStyle: 'circle', backgroundColor: '#a070ff', borderColor: '#a070ff', borderWidth: 1.2, fill:  false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#a070ff', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5 }},
        {{ label: 'Tdie (ºC)', data: {tdie_trend}, pointStyle: 'circle', backgroundColor: '#F46060', borderColor: '#F46060', borderWidth: 1.2, fill:  false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#F46060', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5,yAxisID: 'y2' }},
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        interaction: {{ mode: 'index', intersect: false}},
        tooltip: {{
          mode: 'index',
          intersect: false,
          caretPadding: 20,
          yAlign: 'center',
          backgroundColor: 'rgba(30, 33, 50, 1)',
          titleColor: '#7ab3f0',
          bodyColor: '#e1e7f1',
          padding: 8,
          usePointStyle: true,
      }}
      }},
      scales: {{
        x: {{ 
          ticks: {{
            maxTicksLimit: 12,
            minRotation: 20,
            maxRotation: 20,
            color: 'hsl(220, 83%, 75%)'
          }}, 
          grid: {{ color: 'rgba(255,255,255,0.1)' }},
          border: {{ color: 'rgba(255,255,255,0.2)' }}
        }},
        y: {{ 
          ticks: {{ color: '#a070ff' }}, 
          grid: {{ color: 'rgba(255,255,255,0.1)' }},
          border: {{ color: 'rgba(255,255,255,0.2)' }}
        }},
        y2: {{
          position: 'right',
          min: 0,
          ticks: {{ color: '#F46060' }},
          grid: {{ drawOnChartArea: false }},
          border: {{ color: 'rgba(255,255,255,0.2)' }}
        }},
      }}
    }},
plugins: [
      {{
        id: 'hoverNearest',
        _hoverX: null,
        afterEvent(chart, args) {{
          const {{ event }} = args;
          if (!event) return;

          if (event.type === 'mouseout') {{
            this._hoverX = null;
            chart.setActiveElements([]);
            chart.tooltip.setActiveElements([], {{ x: 0, y: 0 }});
            chart.update();
            return;
          }}

          const points = chart.getElementsAtEventForMode(
            event,
            'index',
            {{ intersect: false }},
            false
          );

          if (points.length) {{
            this._hoverX = points[0].element.x;
            chart.setActiveElements(points);
            chart.tooltip.setActiveElements(points, {{
              x: event.x,
              y: event.y
            }});
          }} else {{
            this._hoverX = null;
            chart.setActiveElements([]);
            chart.tooltip.setActiveElements([], {{ x: 0, y: 0 }});
          }}

          chart.update();
        }},
        afterDraw(chart) {{
          if (this._hoverX === null) return;
          const {{ ctx, chartArea: {{ top, bottom }} }} = chart;
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(this._hoverX, top);
          ctx.lineTo(this._hoverX, bottom);
          ctx.strokeStyle = 'rgba(230, 230, 230, 0.8)';
          ctx.lineWidth = 3;
          ctx.setLineDash([]);
          ctx.stroke();
          ctx.restore();
        }}
      }}
    ]
  }});
</script>
</html>
"""
    return html

@app.route("/ups_widget")
def ups_widget():
    try:
        vars = get_ups_vars()

        status_raw = vars.get("ups.status", "unknown")
        status_label = "Online" if "OL" in status_raw else "En batería" if "OB" in status_raw else status_raw
        status_color = "var(--color-positive)" if "OL" in status_raw else "var(--color-negative)"

        battery_charge = vars.get("battery.charge", "?")
        battery_runtime = int(vars.get("battery.runtime", 0)) // 60
        battery_runtime_low = int(vars.get("battery.runtime.low", 0)) // 60
        input_voltage = vars.get("input.voltage", "?")
        output_voltage = vars.get("output.voltage", "?")
        load_pct = float(vars.get("ups.load", 0))
        nominal_power = float(vars.get("ups.realpower.nominal", 0))
        load_watts = round(load_pct / 100 * nominal_power)

    except Exception as e:
        return f"<p style='color:red'>Error: {e}</p>", 500

    df = pd.read_csv(BASE_DIR / 'metrics.csv')
    df['date'] = pd.to_datetime(df['date'])
    today = pd.Timestamp.now()
    chart_start = today - pd.Timedelta(days=1)

    ups_data = (
        df.loc[
            (df['date'] >= chart_start) &
            (df['battery_charge'].notna()) &
            (df['battery_charge'] > 0),
            ['date', 'battery_charge', 'power']
        ]
        .copy()
        .sort_values('date')
    )

    ups_data['power_3_avg'] = (
        ups_data['power']
        .rolling(window=3)
        .max()
        .round(1)
    )

    ups_data = ups_data.dropna(subset=['power_3_avg'])

    ups_data = ups_data.assign(
        date=ups_data['date'].dt.strftime('%d %H:%M')
    ).to_dict('records')

    ups_data2 = (
        df.loc[
            (df['power'].notna()) &
            (df['power'] > 0),
            ['date', 'power']
        ]
        .copy()
        .sort_values('date')
    )

    labels = [d['date'] for d in ups_data][::3]
    battery_charge_trend = [d['battery_charge'] for d in ups_data][::3]
    power_trend = [d['power_3_avg'] for d in ups_data][::3]

    avg_power = round(ups_data2['power'].mean(), 1)

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500&display=swap" rel="stylesheet">   
<style>
  :root {{
    --color-positive: hsl(105, 48%, 72%);
    --color-negative: hsl(351, 74%, 73%);
  }}
  html, body {{ margin: 0; height: fit-content; background-color: hsl(232, 23%, 18%) !important; font-family: 'Inter', sans-serif; font-size: 13px; }}
  .primary {{ color: #ffffff; }}
  .row {{ margin: 1px 0; font-size: 12px; }}
  p {{ margin: 3px 0; }}
  canvas {{ width: 100% !important; }}
  * {{
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }}
  .status {{
    font-weight: bold;
    /* El color se inyectará por el script o el template */
    color: {status_color}; 
  }}
</style>
</head>
<body>  
  <div style="background: rgba(37,40,60,1); border: 1px solid hsl(232, 23%, 22%); box-shadow: 0px 3px 0px 0px hsl(232, 23%, 18%); border-radius: 8px; padding: 16px 16px;">
  <p><span style="color: #a0b4d0">Status </span><span class="status" style="font-weight:500;">{status_label}</span></p>
  <p><span style="color: #a0b4d0">Runtime </span><span style="font-weight:500; color: #60A2F4">{battery_runtime} min</span><span style="color: #a0b4d0"> // Low Alarm </span><span style="font-weight:500; color: #F46060">{battery_runtime_low} min</span></p>
  <p><span style="color: #a0b4d0">Current Power: </span><span style="font-weight:500; color: #A070FF">{load_watts} W</span><span style="color: #a0b4d0"> // Avg power (last 7d): </span><span style="font-weight:500; color: #A070FF">{avg_power} W</span></p>
  <p><span style="color: #a0b4d0">Output Voltage </span><span style="font-weight:500; color: #60A2F4">{output_voltage} V</span></p>
  <div style="margin-top: 10px;">
  <p class="hl" style="margin-top:8px; font-weight:500; margin:4px 0 0; color:#ffffff">Trends - Last 24h</p>
    <div style="position: relative; height: 200px; width: 100%; margin-top: 5px;">
      <canvas id="chart"></canvas>
    </div>
  </div>
  </div>
</body>
<script>
  window.addEventListener('message', function(e) {{
    if (e.data && e.data.glanceTheme) {{
      var t = e.data.glanceTheme;
      var r = document.documentElement;
      // Actualizamos las variables raíz para que el fondo y colores cambien dinámicamente
      if (t.bgh) r.style.setProperty('--bgh', t.bgh);
      if (t.bgs) r.style.setProperty('--bgs', t.bgs);
      if (t.bgl) r.style.setProperty('--bgl', t.bgl);
      if (t.positive) r.style.setProperty('--color-positive', t.positive);
      if (t.negative) r.style.setProperty('--color-negative', t.negative);
      if (t.primary) r.style.setProperty('--color-primary', t.primary);
    }}
  }});
Chart.defaults.font.family = 'Inter, sans-serif';
  Chart.defaults.font.size = 12;
  new Chart(document.getElementById('chart'), {{
    type: 'line',
    data: {{
      labels: {labels},
      datasets: [
        {{ label: 'Batery Charge (%)', data: {battery_charge_trend}, pointStyle: 'circle', backgroundColor: '#60f4a2', borderColor: '#60f4a2', borderWidth: 1.2, fill:  false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#60f4a2', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5 }},
        {{ label: 'Power (W)', data: {power_trend}, pointStyle: 'circle', backgroundColor: '#a070ff', borderColor: '#a070ff', borderWidth: 1.2, fill: false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#a070ff', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5, yAxisID: 'y2' }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        interaction: {{ mode: 'index', intersect: false}},
        tooltip: {{
          mode: 'index',
          intersect: false,
          caretPadding: 20,
          yAlign: 'center',
          backgroundColor: 'rgba(30, 33, 50, 1)',
          titleColor: '#7ab3f0',
          bodyColor: '#e1e7f1',
          padding: 8,
          usePointStyle: true,
      }}
      }},
      scales: {{
        x: {{ 
          ticks: {{
            maxTicksLimit: 12,
            minRotation: 20,
            maxRotation: 20,
            color: 'hsl(220, 83%, 75%)'
          }}, 
          grid: {{ color: 'rgba(255,255,255,0.1)' }},
          border: {{ color: 'rgba(255,255,255,0.2)' }}
        }},
        y: {{ 
          ticks: {{ color: '#60f4a2' }}, 
          max: 100,
          grid: {{ color: 'rgba(255,255,255,0.1)' }},
          border: {{ color: 'rgba(255,255,255,0.2)' }}
        }},
        y2: {{
          position: 'right',
          max: 200,
          min: 0,
          ticks: {{ color: '#a070ff' }},
          grid: {{ drawOnChartArea: false }},
          border: {{ color: 'rgba(255,255,255,0.2)' }}
        }}
      }}
    }},
plugins: [
      {{
        id: 'hoverNearest',
        _hoverX: null,
        afterEvent(chart, args) {{
          const {{ event }} = args;
          if (!event) return;

          if (event.type === 'mouseout') {{
            this._hoverX = null;
            chart.setActiveElements([]);
            chart.tooltip.setActiveElements([], {{ x: 0, y: 0 }});
            chart.update();
            return;
          }}

          const points = chart.getElementsAtEventForMode(
            event,
            'index',
            {{ intersect: false }},
            false
          );

          if (points.length) {{
            this._hoverX = points[0].element.x;
            chart.setActiveElements(points);
            chart.tooltip.setActiveElements(points, {{
              x: event.x,
              y: event.y
            }});
          }} else {{
            this._hoverX = null;
            chart.setActiveElements([]);
            chart.tooltip.setActiveElements([], {{ x: 0, y: 0 }});
          }}

          chart.update();
        }},
        afterDraw(chart) {{
          if (this._hoverX === null) return;
          const {{ ctx, chartArea: {{ top, bottom }} }} = chart;
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(this._hoverX, top);
          ctx.lineTo(this._hoverX, bottom);
          ctx.strokeStyle = 'rgba(230, 230, 230, 0.8)';
          ctx.lineWidth = 3;
          ctx.setLineDash([]);
          ctx.stroke();
          ctx.restore();
        }}
      }}
    ]
  }});
</script>
</html>
"""
    return html

@app.route("/mem_disk_widget")
def mem_disk_widget():
    df = pd.read_csv(BASE_DIR / 'metrics.csv')
    df['date'] = pd.to_datetime(df['date'])
    today = pd.Timestamp.now()
    chart_start = today - pd.Timedelta(days=2)

    mem_disk_data = (
        df.loc[
            (df['date'] >= chart_start) &
            (df['mem_pct'].notna()) &
            (df['mem_pct'] > 0),
            ['date', 'mem_pct', 'zfs_tank_hdd_pct']
        ]
        .copy()
        .sort_values('date')
    )

    mem_disk_data = mem_disk_data.assign(
        date=mem_disk_data['date'].dt.strftime('%d %H:%M')
    ).rename(columns={
        'mem_pct': 'mem_usage', 'zfs_tank_hdd_pct': 'tank_hdd_usage'
    }).to_dict('records')

    mem_df = (
        df.loc[
            (df['mem_pct'].notna()) &
            (df['mem_pct'] > 0),
            ['date', 'mem_pct', 'zfs_tank_hdd_pct']
        ]
        .copy()
        .sort_values('date')
    )

    used, avail = subprocess.check_output(
    ["zfs", "list", "-H", "-p", "-o", "used,avail", "tank-hdd"],
    text=True
    ).strip().split("\t")

    zfs_total_space = round((int(used)  + int(avail)) / 1024**4, 2)

    labels = [d['date'] for d in mem_disk_data][::5]
    mem_usage_trend = [d['mem_usage'] for d in mem_disk_data][::5]
    tank_hdd_trend = [d['tank_hdd_usage'] for d in mem_disk_data][::5]

    # Extract the maximum RAM usage from the 'mem_usage' column
    max_mem_usage = mem_df['mem_pct'].max()
    max_zfs_usage = round(mem_df['zfs_tank_hdd_pct'].max() * zfs_total_space * 0.01, 2)

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500&display=swap" rel="stylesheet">
<style>
  html, body {{ margin: 0; height: fit-content; background-color: hsl(232, 23%, 18%) !important; font-family: 'Inter', sans-serif; font-size: 13px; }}
  .primary {{ color: #ffffff; }}
  .row {{ margin: 1px 0; font-size: 12px; }}
  p {{ margin: 3px 0; }}
  canvas {{ width: 100% !important; }}
  * {{
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }}
</style>
</head>
<body>  
  <div style="background: rgba(37,40,60,1); border: 1px solid hsl(232, 23%, 22%); box-shadow: 0px 3px 0px 0px hsl(232, 23%, 18%); border-radius: 8px; padding: 16px 16px;">
  <p><span style="color: #a0b4d0">Max RAM usage (last 7d): </span><span style="font-weight:500; color: #A070FF">{max_mem_usage} %</span></p>
  <p><span style="color: #a0b4d0">Max ZFS used capacity (last 7d): </span><span style="font-weight:500; color: #60F4A2">{max_zfs_usage} TB</span><span style="color: #a0b4d0"> out of </span><span style="font-weight:500; color: #60F4A2">{zfs_total_space} TB</span></p>
  <div style="margin-top: 10px;">
  <p class="hl" style="margin-top:8px; font-weight:500; margin:4px 0 0; color:#ffffff">Trends - Last 48h</p>
    <div style="position: relative; height: 180px; width: 100%; margin-top: 5px;">
      <canvas id="chart"></canvas>
    </div>
  </div>
  </div>
</body>
<script>
  window.addEventListener('message', function(e) {{
    if (e.data && e.data.glanceTheme) {{
      var t = e.data.glanceTheme;
      var r = document.documentElement;
      // Actualizamos las variables raíz para que el fondo y colores cambien dinámicamente
      if (t.bgh) r.style.setProperty('--bgh', t.bgh);
      if (t.bgs) r.style.setProperty('--bgs', t.bgs);
      if (t.bgl) r.style.setProperty('--bgl', t.bgl);
      if (t.positive) r.style.setProperty('--color-positive', t.positive);
      if (t.negative) r.style.setProperty('--color-negative', t.negative);
      if (t.primary) r.style.setProperty('--color-primary', t.primary);
    }}
  }});
Chart.defaults.font.family = 'Inter, sans-serif';
  Chart.defaults.font.size = 12;
  new Chart(document.getElementById('chart'), {{
    type: 'line',
    data: {{
      labels: {labels},
      datasets: [
        {{ label: 'RAM usage (%)', data: {mem_usage_trend}, pointStyle: 'circle', backgroundColor: '#a070ff', borderColor: '#a070ff', borderWidth: 1.2, fill:  false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#a070ff', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5 }},
        {{ label: 'ZFS Tank-hdd usage (%)', data: {tank_hdd_trend}, pointStyle: 'circle', backgroundColor: '#60f4a2', borderColor: '#60f4a2', borderWidth: 1.2, fill:  false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#60f4a2', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5 }},
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        interaction: {{ mode: 'index', intersect: false}},
        tooltip: {{
          mode: 'index',
          intersect: false,
          caretPadding: 20,
          yAlign: 'center',
          backgroundColor: 'rgba(30, 33, 50, 1)',
          titleColor: '#7ab3f0',
          bodyColor: '#e1e7f1',
          padding: 8,
          usePointStyle: true,
      }}
      }},
      scales: {{
        x: {{ 
          ticks: {{
            maxTicksLimit: 12,
            minRotation: 20,
            maxRotation: 20,
            color: 'hsl(220, 83%, 75%)'
          }}, 
          grid: {{ color: 'rgba(255,255,255,0.1)' }},
          border: {{ color: 'rgba(255,255,255,0.2)' }}
        }},
        y: {{ 
          ticks: {{ color: 'hsl(220, 83%, 75%)' }}, 
          grid: {{ color: 'rgba(255,255,255,0.1)' }},
          border: {{ color: 'rgba(255,255,255,0.2)' }},
          max: 100,
          min: 0
        }},
      }}
    }},
plugins: [
      {{
        id: 'hoverNearest',
        _hoverX: null,
        afterEvent(chart, args) {{
          const {{ event }} = args;
          if (!event) return;

          if (event.type === 'mouseout') {{
            this._hoverX = null;
            chart.setActiveElements([]);
            chart.tooltip.setActiveElements([], {{ x: 0, y: 0 }});
            chart.update();
            return;
          }}

          const points = chart.getElementsAtEventForMode(
            event,
            'index',
            {{ intersect: false }},
            false
          );

          if (points.length) {{
            this._hoverX = points[0].element.x;
            chart.setActiveElements(points);
            chart.tooltip.setActiveElements(points, {{
              x: event.x,
              y: event.y
            }});
          }} else {{
            this._hoverX = null;
            chart.setActiveElements([]);
            chart.tooltip.setActiveElements([], {{ x: 0, y: 0 }});
          }}

          chart.update();
        }},
        afterDraw(chart) {{
          if (this._hoverX === null) return;
          const {{ ctx, chartArea: {{ top, bottom }} }} = chart;
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(this._hoverX, top);
          ctx.lineTo(this._hoverX, bottom);
          ctx.strokeStyle = 'rgba(230, 230, 230, 0.8)';
          ctx.lineWidth = 3;
          ctx.setLineDash([]);
          ctx.stroke();
          ctx.restore();
        }}
      }}
    ]
  }});
</script>
</html>
"""
    return html

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8084, debug=False)