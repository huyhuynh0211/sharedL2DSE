# L2 leakage of drowsy vs W16 -> results.log
# python3 energy_drowsy.py <out drowsy> <out static W16> [r] [f_tag] [e_wake]
#   r      : drowsy / awake line leakage (assumed 0.16, Flautner 2002 table 4)
#   f_tag  : leakage share of the tag array, always awake (assumed 0.1)
#   e_wake : energy per wake-up (J, assumed 0)
import json
import sys

LOG = "results.log"
P16 = 0.1436                     # W, McPAT 22 nm

d = json.load(open(f"{sys.argv[1]}/run_meta.json"))
b = json.load(open(f"{sys.argv[2]}/run_meta.json"))
r = float(sys.argv[3]) if len(sys.argv) > 3 else 0.16
f_tag = float(sys.argv[4]) if len(sys.argv) > 4 else 0.1
e_wake = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0

t = d["ticks_measured"] / 1e12
t_w16 = b["ticks_measured"] / 1e12
a = d["awake_fraction"]
wakes = d["drowsy_hit_wakes"] + d["drowsy_fill_wakes"]

e_drowsy = P16 * t * (f_tag + (1 - f_tag) * (a + r * (1 - a))) + wakes * e_wake
e_w16 = P16 * t_w16

lines = [f"window {d['window']}, wake_lat {d['wake_lat']}, r {r}, f_tag {f_tag}",
         f"awake fraction (a)  : {100 * a:.2f} %",
         f"hits on drowsy line : {d['drowsy_hit_wakes']}",
         f"run time vs W16     : {100 * (t / t_w16 - 1):+.3f} %",
         f"L2 leakage (drowsy) : {e_drowsy * 1e3:.3f} mJ",
         f"L2 leakage (W16)    : {e_w16 * 1e3:.3f} mJ",
         f"saving              : {100 * (1 - e_drowsy / e_w16):.1f} %"]
with open(LOG, "a") as f:
    f.write("\n== " + " ".join(sys.argv) + "\n" + "\n".join(lines) + "\n")
