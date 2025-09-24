import os
import re
import json
import lizard

def read_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except FileNotFoundError:
        return ''

#查找所有头文件名 
def extract_local_headers(source_code):
    return re.findall(r'#include\s+[<"]([^">]+)[">]', source_code)
 
DEFAULT_INCLUDE_DIRS = [
    r"/usr/include",
    r"/usr/local/include",
    r"/usr/include/x86_64-linux-gnu"
]
 
def find_header_paths(headers, root_dir, include_dirs=None):
    if include_dirs is None:
        include_dirs = DEFAULT_INCLUDE_DIRS
 
    found_paths = []
    searched = set()
 
    for header in headers:
        for dirpath, _, filenames in os.walk(root_dir):
            if header in filenames:
                full_path = os.path.join(dirpath, header)
                found_paths.append(full_path)
                searched.add(header)
                break
 
        # 如果头文件未在根目录下找到，则在默认包含目录中查找
        if header not in searched:
            for base_dir in include_dirs:
                candidate = os.path.join(base_dir, header)
                if os.path.exists(candidate):
                    found_paths.append(candidate)
                    break
    return found_paths

def combine_source_code_and_headers(source_code_path, root_dir):
    source_code = read_file(source_code_path)
    header_names = extract_local_headers(source_code)
    header_paths = find_header_paths(header_names, root_dir)
    combined_code = source_code + "\n\n" + "\n\n".join(read_file(h) for h in header_paths)
    return combined_code, header_paths

def analyze_with_lizard(combined_code_path):
    result = lizard.analyze_file(combined_code_path)
    loc = result.nloc
    function_count = len(result.function_list)
    avg_func_length = sum(f.length for f in result.function_list) / function_count if function_count else 0
    max_cyclomatic = max((f.cyclomatic_complexity for f in result.function_list), default=0)
    max_nest = max((f.max_nesting_depth for f in result.function_list), default=0)
    return {
        'loc': loc,
        'function_count': function_count,
        'average_function_length': avg_func_length,
        'max_cyclomatic_complexity': max_cyclomatic,
        'max_nesting_depth': max_nest
    }

def log_normalize(x, x_max):
    import math
    return round(math.log1p(x) / math.log1p(x_max), 4) if x_max else 0.0

def compute_max_source_metrics(tasks):
    max_vals = {
        'loc': 0,
        'function_count': 0,
        'average_function_length': 0,
        'max_cyclomatic_complexity': 0,
        'max_nesting_depth': 0
    }

    for task in tasks:
        for key in max_vals:
            if key in task:
                max_vals[key] = max(max_vals[key], task[key])

    return max_vals

def process_tasks_with_source_score(json_path, project_root, output_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        tasks = json.load(f)

    results = []

    # === 分析所有任务，提取源代码复杂度特征 ===
    for task in tasks:
        inputs = task.get("inputs", [])
        source_files = [i for i in inputs if i.endswith('.c')]
        if not source_files:
            task.update({
                'loc': 0,
                'function_count': 0,
                'average_function_length': 0,
                'max_cyclomatic_complexity': 0,
                'max_nesting_depth': 0
            })
            results.append(task)
            continue

        source_file = source_files[0]
        combined_code, _ = combine_source_code_and_headers(source_file, project_root)
        temp_combined_path = "/tmp/combined_code.c"
        with open(temp_combined_path, 'w', encoding='utf-8') as f:
            f.write(combined_code)

        result = analyze_with_lizard(temp_combined_path)
        task.update(result)
        results.append(task)

    # === 提取最大值，用于归一化 ===
    max_vals = compute_max_source_metrics(results)

    # === 计算归一化得分 ===
    for task in results:
        norm_loc = log_normalize(task['loc'], max_vals['loc'])
        norm_func = log_normalize(task['function_count'], max_vals['function_count'])
        norm_avg_func_len = log_normalize(task['average_function_length'], max_vals['average_function_length'])
        norm_cyclomatic = log_normalize(task['max_cyclomatic_complexity'], max_vals['max_cyclomatic_complexity'])
        norm_nesting = log_normalize(task['max_nesting_depth'], max_vals['max_nesting_depth'])

        # 可调整权重
        w1, w2, w3, w4, w5 = 0.2, 0.2, 0.15, 0.3, 0.15
        score = round(
            w1 * norm_loc +
            w2 * norm_func +
            w3 * norm_avg_func_len +
            w4 * norm_cyclomatic +
            w5 * norm_nesting, 5
        )
        task["normalized_source_score"] = score

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    return len(results)

# 执行批量处理任务
process_tasks_with_source_score(
    json_path=r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\edge_costs\full_build_commands.json",
    project_root=r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2",
    output_path = r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\edge_costs\build_code_score.json"
)
print("处理完成，结果保存在 build_code_score.json")

