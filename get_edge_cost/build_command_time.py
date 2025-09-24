import re
import json
import math

def extract_opt_level(command: str) -> int:
    """
    提取命令中出现的-OX优化等级，映射为整数得分：
     -O0: 1, -O1: 2, -O2: 3, -O3: 4, -Ofast: 4
    """
    if not command:
            return 1
    opt_map = {'0': 1, '1': 2, '2': 3, '3': 4, 'fast': 4}
    matches = re.findall(r'-O(\w+)', command.lower())
    scores = [opt_map.get(m, 1) for m in matches]
    return max(scores) if scores else 1

def detect_command_type_score(command: str) -> str:
    """
    根据构建命令判定任务类型，返回对应权重分数：
    - Compile: 1.0
    - StaticLink: 1.5
    - DynamicLink: 2.0
    - LTO: 3.5
    - Unknown: 1.0
    """
    cmd_lower = command.lower()

    # LTO 优先识别
    if "-flto" in cmd_lower or "-fwhole-program" in cmd_lower:
        return 3.5

    # 静态链接（典型 ar 工具）
    if "ar " in cmd_lower or "ar.exe" in cmd_lower:
        return 1.5

    # 编译任务（带 -c 且输入为 .c/.cpp 文件）
    if "-c" in cmd_lower:
        return 1.0

    # 动态链接任务（gcc/g++/ld 等生成最终目标文件）
    if any(link_kw in cmd_lower for link_kw in ["gcc", "g++", "cc", "ld"]):
        return 2.0

    return 1.0

def compute_max_metrics(tasks: list) -> dict:
    """
    计算任务列表中的最大输入文件数、输出文件数和命令长度
    """
    max_input_file = 0
    max_output_file = 0
    max_cmd_len = 0

    for task in tasks:
        inputs = task.get("inputs", [])
        outputs = task.get("outputs", [])
        command = task.get("full_command", "")

        input_count = len([i for i in inputs if i != "||"])
        output_count = len(outputs)
        cmd_len = len(command)

        if input_count > max_input_file:
            max_input_file = input_count
        if output_count > max_output_file:
            max_output_file = output_count
        if cmd_len > max_cmd_len:
            max_cmd_len = cmd_len

    return {
        "max_input_file": max_input_file,
        "max_output_file": max_output_file,
        "max_cmd_len": max_cmd_len,
    }

def log_normalize(x, x_max):
    if x_max == 0:
        return 0.0
    return math.log1p(x) / math.log1p(x_max)  # log1p(x) = log(1 + x)

def min_max_normalize(value, min_val, max_val):
    if max_val == min_val:
        return 0.0
    normalized = (value - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, normalized))  

def model_build_declaration(task: dict, max_metrics: dict) -> dict:
    command = task.get("full_command", "")
    inputs = task.get("inputs", [])
    outputs = task.get("outputs", [])

    command_length = len(command)
    opt_level = extract_opt_level(command)
    command_type_score = detect_command_type_score(command)
    count_input_file = len([i for i in inputs if i != "||"])
    count_output_file = len(outputs)

    # 使用 log 归一化处理偏态分布的文件数量
    norm_input_file = log_normalize(count_input_file, max_metrics["max_input_file"])
    norm_output_file = log_normalize(count_output_file, max_metrics["max_output_file"])
    norm_command_length = log_normalize(command_length, max_metrics["max_cmd_len"])

    # 使用 min-max 归一化处理范围明确的小范围特征
    norm_opt_level = min_max_normalize(opt_level, 1, 4)
    norm_command_type = min_max_normalize(command_type_score, 1.0, 3.5)

    w1, w2, w3, w4, w5 = 0.25, 0.15, 0.25, 0.20, 0.15

    build_decl_score = (
        w1 * norm_input_file +
        w2 * norm_output_file +
        w3 * norm_command_length +
        w4 * norm_opt_level +
        w5 * norm_command_type
    )

    return {
        "outputs": outputs,
        "inputs": inputs,
        "rule": task.get("rule", ""),
        "full_command": command,
        "norm_input_file": float(f"{norm_input_file:.5f}"),
        "norm_output_file": float(f"{norm_output_file:.5f}"),
        "norm_command_length": float(f"{norm_command_length:.5f}"),
        "norm_opt_level": float(f"{norm_opt_level:.5f}"),
        "norm_command_type": float(f"{norm_command_type:.5f}"),
        "build_decl_score": float(f"{build_decl_score:.5f}"),
    }

def batch_model_build_declaration(tasks: list) -> list:
    max_metrics = compute_max_metrics(tasks)
    results = []
    for task in tasks:
        score = model_build_declaration(task, max_metrics)
        results.append(score)
    return results

if __name__ == "__main__":
    input_path = r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\edge_costs\full_build_commands.json"
    output_path = r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\edge_costs\build_command_score.json"

    with open(input_path, encoding="utf-8") as f:
        raw_tasks = json.load(f)

    processed_tasks = batch_model_build_declaration(raw_tasks)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(processed_tasks, f, indent=2, ensure_ascii=False)

    print(f"已成功处理 {len(processed_tasks)} 个构建任务，包含归一化评分，输出至 {output_path}")
