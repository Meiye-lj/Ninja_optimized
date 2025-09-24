import json

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(data, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def outputs_key(task):
    return '|'.join(task.get('outputs', []))

def combine_scores(decl_path, source_path, output_path, w_decl=0.5, w_src=0.5):
    decl_tasks = load_json(decl_path)
    source_tasks = load_json(source_path)

    # 构建映射：outputs -> normalized_source_score
    source_map = {
        outputs_key(task): task.get('normalized_source_score', 0.0)
        for task in source_tasks
    }

    combined = []
    for task in decl_tasks:
        if task.get('rule') == "phony":
            task['estimated_build_time'] = 0.0
            task['normalized_source_score'] = 0.0
            task['build_decl_score'] = 0.0
        else:
            key = outputs_key(task)
            decl_score = task.get('build_decl_score', 0.0)
            source_score = source_map.get(key, 0.0)
            estimated = round(w_decl * decl_score + w_src * source_score, 5)

            task['normalized_source_score'] = source_score
            task['estimated_build_time'] = estimated

        # 🔍 无论是否是 phony，都清除中间字段
        for field in [
            "norm_input_file",
            "norm_output_file",
            "norm_command_length",
            "norm_opt_level",
            "norm_command_type"
        ]:
            task.pop(field, None)

        combined.append(task)

    save_json(combined, output_path)
    print(f"✅ 合并完成，写入 {output_path}，共处理 {len(combined)} 个任务。")


if __name__ == "__main__":
    combine_scores(
        decl_path=r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\edge_costs\build_command_score.json",
        source_path=r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\edge_costs\build_code_score.json",
        output_path=r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\edge_costs\build_time_estimation.json"
    )


