"""Quick chart: San Antonio call trends Jan 2025 -> May 2026 (partial)."""
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

data = [
    ("2025-01", 394, 246, 43),
    ("2025-02", 391, 239, 44),
    ("2025-03", 618, 369, 72),
    ("2025-04", 559, 344, 76),
    ("2025-05", 567, 327, 91),
    ("2025-06", 523, 305, 56),
    ("2025-07", 426, 254, 43),
    ("2025-08", 460, 266, 53),
    ("2025-09", 447, 241, 53),
    ("2025-10", 515, 334, 46),
    ("2025-11", 341, 213, 43),
    ("2025-12", 279, 152, 46),
    ("2026-01", 316, 190, 40),
    ("2026-02", 313, 178, 50),
    ("2026-03", 421, 242, 55),
    ("2026-04", 408, 198, 70),
    ("2026-05*", 61, 28, 21),
]

months   = [r[0] for r in data]
total    = [r[1] for r in data]
qualified= [r[2] for r in data]
missed   = [r[3] for r in data]

fig, ax = plt.subplots(figsize=(12, 5.5))

ax.plot(months, total,     marker="o", linewidth=2.2, color="#1f4e79", label="Total calls")
ax.plot(months, qualified, marker="o", linewidth=2.0, color="#2e8b57", label="Qualified (60s+)")
ax.plot(months, missed,    marker="o", linewidth=1.8, color="#c0392b", label="Missed")

for i, v in enumerate(total):
    ax.annotate(str(v), (i, v), textcoords="offset points", xytext=(0, 8),
                ha="center", fontsize=8, color="#1f4e79")

ax.set_title("San Antonio — Monthly Call Trends (Jan 2025 – May 2026)", fontsize=13, fontweight="bold")
ax.set_ylabel("Calls")
ax.set_xlabel("Month")
ax.yaxis.set_major_locator(MaxNLocator(integer=True))
ax.grid(True, axis="y", linestyle="--", alpha=0.4)
ax.legend(loc="upper right", frameon=False)
plt.xticks(rotation=45, ha="right")
ax.text(0.01, -0.28, "* May 2026 is partial (through 5/6)",
        transform=ax.transAxes, fontsize=8, style="italic", color="#555")

plt.tight_layout()

out = Path(r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest\Supabase Data Hub\output\[C] SA Call Trends 5-6-2026.png")
plt.savefig(out, dpi=160, bbox_inches="tight")
print(f"Saved: {out}")
