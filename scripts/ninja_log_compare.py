import pandas as pd

def parse_ninja_log(file_path):
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) != 5:
                continue
            start, end, pid, path, h = parts
            duration = int(end) - int(start)
            records.append({
                "path": path,
                "start": int(start),
                "end": int(end),
                "duration": duration,
                "hash": h
            })
    return pd.DataFrame(records)

def compare_logs(original_log, optimized_log, output_txt="ninja_compare.txt"):
    df_orig = parse_ninja_log(original_log)
    df_opt = parse_ninja_log(optimized_log)

    # 显示任务总数
    total_tasks_orig = df_orig.shape[0]
    total_tasks_opt = df_opt.shape[0]

    # 查找缺失任务
    missing_in_opt = sorted(set(df_orig["path"]) - set(df_opt["path"]))
    missing_in_orig = sorted(set(df_opt["path"]) - set(df_orig["path"]))

    # 合并对比相同任务
    merged = pd.merge(df_orig, df_opt, on="path", suffixes=("_orig", "_opt"))
    merged["delta"] = merged["duration_orig"] - merged["duration_opt"]
    merged["speedup"] = merged["duration_orig"] / merged["duration_opt"]

    # 总体耗时
    total_orig_duration = df_orig["duration"].sum()
    total_opt_duration = df_opt["duration"].sum()
    overall_speedup = total_orig_duration / total_opt_duration

    # 准备输出内容
    output_lines = []
    output_lines.append("===== 构建任务总数 =====")
    output_lines.append(f"原版任务总数: {total_tasks_orig}")
    output_lines.append(f"优化版任务总数: {total_tasks_opt}\n")

    output_lines.append("===== 缺失任务 =====")
    output_lines.append(f"优化版缺失的任务 ({len(missing_in_opt)}):")
    output_lines.extend(missing_in_opt if missing_in_opt else ["None"])
    output_lines.append(f"\n原版缺失的任务 ({len(missing_in_orig)}):")
    output_lines.extend(missing_in_orig if missing_in_orig else ["None"])

    output_lines.append("\n===== 构建耗时对比 (仅共有任务) =====")
    output_lines.append(merged[["path", "duration_orig", "duration_opt", "delta", "speedup"]].to_string(index=False))

    output_lines.append("\n===== 总体统计 =====")
    output_lines.append(f"原版总耗时: {total_orig_duration}")
    output_lines.append(f"优化版总耗时: {total_opt_duration}")
    output_lines.append(f"整体加速比: {overall_speedup:.2f}x")

    output_text = "\n".join(output_lines)

    # 打印到终端
    #print(output_text)

    # 保存到 txt 文件
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"\n✅ 对比信息已保存到: {output_txt}")

    return merged

if __name__ == "__main__":
    merged = compare_logs(
        "/home/enovoleekira/function_test/project/Catch2/build_original/.ninja_log",
        "/home/enovoleekira/function_test/project/Catch2/build_optimized/.ninja_log",
        output_txt="/home/enovoleekira/function_test/result/Catch2_compare.txt"
    )
