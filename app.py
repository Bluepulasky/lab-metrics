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

    df = pd.read_csv(BASE_DIR / 'ups.csv')
    df['date'] = pd.to_datetime(df['date'])
    today = pd.Timestamp.now().normalize()
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

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

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
  <div class="model" style="font-size: 15px;">CyberPower CP900</div>
  
  <div class="row">
    <span class="label">Estado</span>
    <span class="status">{status_label}</span>
  </div>
  
  <div class="row">
    <span class="label">Batería</span>
    <span class="value">{battery_charge}%</span>
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
    <span class="label">Tensión entrada</span>
    <span class="value">{input_voltage} V</span>
  </div>
  
  <div class="row">
    <span class="label">Tensión salida</span>
    <span class="value">{output_voltage} V</span>
  </div>

  <div style="margin-top: 15px;">
  <p class="primary" style="margin-top:8px; font-size: 16px;">Trends - Last 24h</p>
    <div style="position: relative; height: 300px; width: 100%; margin-top: 5px;">
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
          ticks: {{ display: false }}, 
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
          max: 300,
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8084, debug=False)