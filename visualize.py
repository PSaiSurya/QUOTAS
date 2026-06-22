import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import numpy as np

# Academic formatting standards
sns.set_theme(style="whitegrid", context="paper", font_scale=1.2)
CSV_FILE = "nist_pqc_ot_benchmarks.csv"

def generate_charts():
    if not os.path.exists(CSV_FILE):
        print("[-] CSV file not found. Run benchmark.py first.")
        return

    # Load and clean data
    df = pd.read_csv(CSV_FILE)
    df['Avg_Latency_ms'] = pd.to_numeric(df['Avg_Latency_ms'], errors='coerce')
    df['Successful_Polls'] = pd.to_numeric(df['Successful_Polls'], errors='coerce')
    
    # [BUG FIX]: Dynamically extract exact hardware names from the CSV to prevent string mismatches
    actual_hw = df['PLC_Hardware_Profile'].unique().tolist()
    
    # Force logical progression based on CPU power, grabbing whatever names actually exist in the CSV
    cpu_order_mapping = ['micro', 'legacy', 'mid', 'high']
    hardware_order = []
    for target in cpu_order_mapping:
        for hw in actual_hw:
            if target in hw.lower() and hw not in hardware_order:
                hardware_order.append(hw)
    
    # Catch any extras that didn't match the mapping
    hardware_order += [hw for hw in actual_hw if hw not in hardware_order]

    # Apply Categorical ordering
    df['PLC_Hardware_Profile'] = pd.Categorical(df['PLC_Hardware_Profile'], categories=hardware_order, ordered=True)
    df_success = df[df['Status'] == 'SUCCESS'].copy()

    os.makedirs("graphs", exist_ok=True)
    protocols = df['Protocol'].unique()

    # ========================================================================
    # 1. LATENCY DISTRIBUTION BOXPLOTS (Log Scale)
    # ========================================================================
    for proto in protocols:
        plt.figure(figsize=(14, 7))
        ax = sns.boxplot(
            data=df_success[df_success['Protocol'] == proto], 
            x="Cipher_Suite", y="Avg_Latency_ms", hue="PLC_Hardware_Profile", 
            palette="viridis", showfliers=False, linewidth=1.5
        )
        plt.title(f"{proto.upper()} Latency Distribution across PQC Suites", pad=15, fontweight='bold', fontsize=16)
        plt.xticks(rotation=25, ha='right', fontsize=11)
        plt.yscale("log")
        plt.ylabel("Average Latency (ms) [Log Scale]", fontsize=12)
        plt.xlabel("NIST Cryptographic Suite", fontsize=12)
        plt.legend(title="Hardware Profile", bbox_to_anchor=(1.01, 1), loc='upper left')
        plt.tight_layout()
        plt.savefig(f"graphs/1_latency_boxplot_{proto}.png", dpi=300, bbox_inches='tight')
        plt.close()

    # ========================================================================
    # 2. CRYPTOGRAPHIC DoS HEATMAP (Replaces Bar Chart)
    # ========================================================================
    # Calculate percentage of successful connections
    success_rates = df.groupby(['PLC_Hardware_Profile', 'Cipher_Suite'], observed=False)['Status'].apply(
        lambda x: (x == 'SUCCESS').mean() * 100
    ).unstack()

    plt.figure(figsize=(10, 6))
    sns.heatmap(success_rates, annot=True, fmt=".1f", cmap="RdYlGn", vmin=0, vmax=100, linewidths=.5)
    plt.title("Cryptographic DoS: Connection Success Rate (%)", pad=15, fontweight='bold', fontsize=14)
    plt.ylabel("Hardware Profile")
    plt.xlabel("Cryptographic Suite")
    plt.xticks(rotation=30, ha='right')
    plt.tight_layout()
    plt.savefig("graphs/2_success_rate_heatmap.png", dpi=300)
    plt.close()

    # ========================================================================
    # 3. PROTOCOL OVERHEAD WITH JITTER (Error Bars)
    # ========================================================================
    for hw in hardware_order:
        hw_data = df_success[df_success['PLC_Hardware_Profile'] == hw]
        if hw_data.empty: continue 
            
        plt.figure(figsize=(12, 6))
        # errorbar='sd' adds the Standard Deviation lines, representing network Jitter
        sns.barplot(
            data=hw_data, x="Protocol", y="Avg_Latency_ms", hue="Cipher_Suite", 
            palette="mako", errorbar='sd', capsize=0.1, err_kws={'linewidth': 1.5}
        )
        plt.title(f"Protocol Overhead & Jitter under PQC ({hw.upper()})", pad=15, fontweight='bold', fontsize=14)
        plt.ylabel("Average Latency (ms) + StdDev Jitter", fontsize=12)
        plt.xlabel("Industrial Protocol", fontsize=12)
        plt.legend(title="Cipher Suite", bbox_to_anchor=(1.01, 1), loc='upper left')
        plt.tight_layout()
        plt.savefig(f"graphs/3_protocol_overhead_{hw}.png", dpi=300, bbox_inches='tight')
        plt.close()

    # ========================================================================
    # 4. CPU SCALING BOUNDARY (Line Chart)
    # ========================================================================
    plt.figure(figsize=(12, 6))
    # Using Modbus as the standard baseline payload for CPU scaling
    cpu_data = df_success[df_success['Protocol'] == 'modbus']
    sns.lineplot(
        data=cpu_data, x="PLC_Hardware_Profile", y="Avg_Latency_ms", 
        hue="Cipher_Suite", marker="o", linewidth=2.5, markersize=8, palette="tab10"
    )
    plt.title("The Cryptographic Starvation Boundary (Modbus Payload)", pad=15, fontweight='bold', fontsize=14)
    plt.ylabel("Latency (ms) [Log Scale]", fontsize=12)
    plt.xlabel("Hardware Profile (Increasing CPU Limit →)", fontsize=12)
    plt.yscale("log")
    plt.grid(True, which="both", ls="--", alpha=0.5)
    plt.legend(title="Cipher Suite", bbox_to_anchor=(1.01, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig("graphs/4_cpu_scaling_boundary.png", dpi=300, bbox_inches='tight')
    plt.close()

# ========================================================================
    # 5. TAIL LATENCY ECDF (Networking Gold Standard)
    # ========================================================================
    mid_tier_data = df_success[df_success['PLC_Hardware_Profile'] == hardware_order[2]] if len(hardware_order) > 2 else df_success
    
    plt.figure(figsize=(10, 6))
    ax = sns.ecdfplot(data=mid_tier_data, x="Avg_Latency_ms", hue="Cipher_Suite", palette="Set1", linewidth=2)
    
    # Add the 99th percentile line
    plt.axhline(0.99, color='red', linestyle='--', alpha=0.7, label='99th Percentile')
    
    plt.title("Empirical Cumulative Distribution (Tail Latency - Mid Tier PLC)", pad=15, fontweight='bold')
    plt.ylabel("Probability", fontsize=12)
    plt.xlabel("Latency (ms)", fontsize=12)
    plt.xlim(0, mid_tier_data['Avg_Latency_ms'].quantile(0.995)) 
    
    # [BUG FIX]: Use sns.move_legend to safely combine both legends without overwriting
    sns.move_legend(ax, "upper left", bbox_to_anchor=(1.01, 1), title="Legend")
    
    plt.tight_layout()
    plt.savefig("graphs/5_tail_latency_ecdf.png", dpi=300, bbox_inches='tight')
    plt.close()

    print(f"\n[+] Elite Thesis charts successfully generated in the '/graphs' directory!")
    print(f"    -> Fixed hardware naming mismatches automatically.")
    print(f"    -> Generated Heatmaps, Jitter Overlays, ECDF, and CPU Scaling curves.")

if __name__ == "__main__":
    generate_charts()
