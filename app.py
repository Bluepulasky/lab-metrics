from flask import Flask, jsonify, render_template_string
import socket
import pandas as pd
from datetime import datetime
import csv
import os
from pathlib import Path

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

    df_filtered = df[(df['date'] >= chart_start)].copy()

    cpu_data = []
    for _, row in df_filtered.iterrows():
        cpu_avg_trend = row['cpu_avg_10s']
        if pd.notna(cpu_avg_trend) and cpu_avg_trend > 0:
            cpu_data.append({
                    "date": str(row['date'].strftime('%d %H:%M')),
                    "cpu_usage": cpu_avg_trend
                })
    cpu_data.sort(key=lambda x: x['date'])

    labels = [d['date'] for d in cpu_data]
    cpu_usage_trend = [d['cpu_usage'] for d in cpu_data]

    # Convert the list of dictionaries to a DataFrame for easier manipulation
    cpu_df = pd.DataFrame(cpu_data)

    # Extract the maximum CPU usage from the 'cpu_usage' column
    max_cpu_usage = cpu_df['cpu_usage'].max()
    percentile_95_cpu_usage = round(cpu_df['cpu_usage'].quantile(0.95),1)

    status_color1 = "var(--color-negative)" if max_cpu_usage > 90 else "var(--color-positive)"
    status_color2 = "var(--color-negative)" if percentile_95_cpu_usage > 90 else "var(--color-positive)"

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
    --bgh: 232;
    --bgs: 23%;
    --bgl: 18%;
    --color-primary: hsl(220, 83%, 75%);
    --color-positive: hsl(105, 48%, 72%);
    --color-negative: hsl(351, 74%, 73%);
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }}

  body {{
    background-color: hsl(var(--bgh), var(--bgs), var(--bgl)) !important;
    color: var(--color-primary) !important;
    font-family: monospace;
    font-size: 14px;
    padding: 4px;
  }}

  .model {{
    font-weight: 500;
    text-align: center;
    padding: 0 0 6px 0;
    border-bottom: 1px solid rgba(255,2255,255,0.15);
    margin-bottom: 6px;
    text-transform: uppercase;
    letterspacing: 1px;
  }}

  .row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 2px 0;
    border-bottom: 1px solid rgba(255,255,255,0.15);
  }}

  .row:last-child {{
    border-bottom: none;
  }}

  .label {{
    font-weight: 500;
    color: var(--color-primary);
  }}

  .value {{
    opacity: 0.75; /* Tal como el .log-content del primer HTML */
  }}

  .status1 {{
    font-weight: bold;
    /* El color se inyectará por el script o el template */
    color: {status_color1}; 
  }}

  .status2 {{
    font-weight: bold;
    /* El color se inyectará por el script o el template */
    color: {status_color2}; 
  }}
</style>
</head>
<body>  
  <div class="row">
    <span class="label">Max CPU usage (10s avg) % (last 7d)</span>
    <span class="status1">{max_cpu_usage}</span>
  </div>

  <div class="row">
    <span class="label">95%pct CPU usage (10s avg) % (last 7d)</span>
    <span class="status2">{percentile_95_cpu_usage}</span>
  </div>

  <div style="margin-top: 15px;">
  <p class="primary" style="margin-top:8px; font-size: 16px;">Trend - Last 24h</p>
    <div style="position: relative; height: 200px; width: 100%; margin-top: 5px;">
      <canvas id="chart"></canvas>
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
        {{ label: 'CPU 10s avg (%)', data: {cpu_usage_trend}, pointStyle: 'circle', backgroundColor: '#4DA3FF', borderColor: '#4DA3FF', fill:  false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#4DA3FF', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5 }},
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
            maxRotation: 0,
            maxTicksLimit: 12,
            minRotation: 30,
            maxRotation: 30,
            color: 'hsl(220, 83%, 75%)'
          }}, 
          grid: {{ color: 'rgba(255,255,255,0.1)' }},
          border: {{ color: 'rgba(255,255,255,0.2)' }}
        }},
        y: {{ 
          ticks: {{ color: 'hsl(220, 83%, 75%)' }}, 
          grid: {{ color: 'rgba(255,255,255,0.1)' }},
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

    df_filtered = df[(df['date'] >= chart_start)].copy()

    ups_data = []
    for _, row in df_filtered.iterrows():
        battery_charge_trend = row['battery_charge']
        power_trend = row['power']
        if pd.notna(battery_charge_trend) and battery_charge_trend > 0:
            ups_data.append({
                    "date": str(row['date'].strftime('%d %H:%M')),
                    "battery_charge": round(battery_charge_trend, 1),
                    "power": round(power_trend, 1)
                })
    ups_data.sort(key=lambda x: x['date'])

    labels = [d['date'] for d in ups_data]
    battery_charge_trend = [d['battery_charge'] for d in ups_data]
    power_trend = [d['power'] for d in ups_data]

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
    --bgh: 232;
    --bgs: 23%;
    --bgl: 18%;
    --color-primary: hsl(220, 83%, 75%);
    --color-positive: hsl(105, 48%, 72%);
    --color-negative: hsl(351, 74%, 73%);
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }}

  body {{
    background-color: hsl(var(--bgh), var(--bgs), var(--bgl)) !important;
    color: var(--color-primary) !important;
    font-family: monospace;
    font-size: 14px;
    padding: 4px;
  }}

  .model {{
    font-weight: 500;
    text-align: center;
    padding: 0 0 6px 0;
    border-bottom: 1px solid rgba(255,2255,255,0.15);
    margin-bottom: 6px;
    text-transform: uppercase;
    letterspacing: 1px;
  }}

  .row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 2px 0;
    border-bottom: 1px solid rgba(255,255,255,0.15);
  }}

  .row:last-child {{
    border-bottom: none;
  }}

  .label {{
    font-weight: 500;
    color: var(--color-primary);
  }}

  .value {{
    opacity: 0.75; /* Tal como el .log-content del primer HTML */
  }}

  .status {{
    font-weight: bold;
    /* El color se inyectará por el script o el template */
    color: {status_color}; 
  }}
</style>
</head>
<body> 
  <div class="row">
    <span class="label">Estado</span>
    <span class="status">{status_label}</span>
  </div>
   
  <div class="row">
    <span class="label">Autonomía</span>
    <span class="value">{battery_runtime} min</span>
  </div>
  
  <div class="row">
    <span class="label">Corte a</span>
    <span class="value">{battery_runtime_low} min</span>
  </div>
  
  <div class="row">
    <span class="label">Carga</span>
    <span class="value">{load_watts} W ({load_pct:.0f}%)</span>
  </div>
   
  <div class="row">
    <span class="label">Tensión salida</span>
    <span class="value">{output_voltage} V</span>
  </div>

  <div style="margin-top: 15px;">
  <p class="primary" style="margin-top:8px; font-size: 16px;">Trends - Last 24h</p>
    <div style="position: relative; height: 230px; width: 100%; margin-top: 5px;">
      <canvas id="chart"></canvas>
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
        {{ label: 'Batery Charge (%)', data: {battery_charge_trend}, pointStyle: 'circle', backgroundColor: '#60f4a2', borderColor: '#60f4a2', fill:  false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#60f4a2', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5 }},
        {{ label: 'Power (W)', data: {power_trend}, pointStyle: 'circle', backgroundColor: '#a070ff', borderColor: '#a070ff', fill: false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#a070ff', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5, yAxisID: 'y2' }}
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
            maxRotation: 0,
            maxTicksLimit: 12,
            minRotation: 30,
            maxRotation: 30,
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

    df_filtered = df[(df['date'] >= chart_start)].copy()

    mem_disk_data = []
    for _, row in df_filtered.iterrows():
        mem_trend = row['mem_pct']
        disc_tank_hdd_trend = row['zfs_tank_hdd_pct']
        if pd.notna(mem_trend) and mem_trend > 0:
            mem_disk_data.append({
                    "date": str(row['date'].strftime('%d %H:%M')),
                    "mem_usage": mem_trend,
                    "tank_hdd_usage": disc_tank_hdd_trend
                })
    mem_disk_data.sort(key=lambda x: x['date'])

    labels = [d['date'] for d in mem_disk_data][::5]
    mem_usage_trend = [d['mem_usage'] for d in mem_disk_data][::5]
    tank_hdd_trend = [d['tank_hdd_usage'] for d in mem_disk_data][::5]

    # Convert the list of dictionaries to a DataFrame for easier manipulation
    mem_df = pd.DataFrame(mem_disk_data)

    # Extract the maximum RAM usage from the 'mem_usage' column
    max_mem_usage = mem_df['mem_usage'].max()

    status_color = "var(--color-negative)" if max_mem_usage > 90 else "var(--color-positive)"

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
    --bgh: 232;
    --bgs: 23%;
    --bgl: 18%;
    --color-primary: hsl(220, 83%, 75%);
    --color-positive: hsl(105, 48%, 72%);
    --color-negative: hsl(351, 74%, 73%);
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }}

  body {{
    background-color: hsl(var(--bgh), var(--bgs), var(--bgl)) !important;
    color: var(--color-primary) !important;
    font-family: monospace;
    font-size: 14px;
    padding: 4px;
  }}

  .model {{
    font-weight: 500;
    text-align: center;
    padding: 0 0 6px 0;
    border-bottom: 1px solid rgba(255,2255,255,0.15);
    margin-bottom: 6px;
    text-transform: uppercase;
    letterspacing: 1px;
  }}

  .row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 2px 0;
    border-bottom: 1px solid rgba(255,255,255,0.15);
  }}

  .row:last-child {{
    border-bottom: none;
  }}

  .label {{
    font-weight: 500;
    color: var(--color-primary);
  }}

  .value {{
    opacity: 0.75; /* Tal como el .log-content del primer HTML */
  }}

  .status {{
    font-weight: bold;
    /* El color se inyectará por el script o el template */
    color: {status_color}; 
  }}

</style>
</head>
<body>  
  <div class="row">
    <span class="label">Max RAM usage % (last 7d)</span>
    <span class="status">{max_mem_usage}</span>
  </div>

  <div style="margin-top: 15px;">
  <p class="primary" style="margin-top:8px; font-size: 16px;">Trend - Last 48h</p>
    <div style="position: relative; height: 200px; width: 100%; margin-top: 5px;">
      <canvas id="chart"></canvas>
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
        {{ label: 'Memory usage (%)', data: {mem_usage_trend}, pointStyle: 'circle', backgroundColor: '#a070ff', borderColor: '#a070ff', fill:  false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#a070ff', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5 }},
        {{ label: 'ZFS Tank-hdd usage (%)', data: {tank_hdd_trend}, pointStyle: 'circle', backgroundColor: '#60f4a2', borderColor: '#60f4a2', fill:  false, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#60f4a2', pointHoverBorderWidth: 2, pointHoverBorderColor: '#ffffff', tension: 0.5 }},
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
            maxRotation: 0,
            maxTicksLimit: 12,
            minRotation: 30,
            maxRotation: 30,
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