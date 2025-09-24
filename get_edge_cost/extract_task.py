import os
import re
import json

def parse_rules_ninja(rules_path):
    """解析 rules.ninja 文件，返回 {rule_name: command_template}"""
    rules = {}
    current_rule = None
    with open(rules_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith("rule "):
                current_rule = line.split()[1]
            elif current_rule and line.startswith("command ="):
                command = line[len("command ="):].strip()
                rules[current_rule] = command
                current_rule = None  
    return rules

def parse_build_ninja(build_path):
    """解析 build.ninja，提取每个构建块的目标、输入、规则名"""
    builds = []
    current = None
    with open(build_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith("build "):
                # build foo.o: C_COMPILER foo.c
                parts = line[len("build "):].split(":")
                if len(parts) < 2:
                    continue
                output = parts[0].strip().split()
                rule_and_inputs = parts[1].strip().split()
                rule = rule_and_inputs[0]
                inputs = rule_and_inputs[1:]
                current = {
                    "outputs": output,
                    "inputs": inputs,
                    "rule": rule
                }
                builds.append(current)
    return builds

def combine_with_rule_commands(builds, rules_dict):
    """将规则 command 填入构建项"""
    for b in builds:
        rule = b["rule"]
        b["command_template"] = rules_dict.get(rule, "")
    return builds

def main():
    build_ninja_path = r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\build_optimized\build.ninja"
    rule_ninja_path = os.path.join("CMakeFiles", r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\build_optimized\CMakeFiles\rules.ninja")

    if not os.path.exists(build_ninja_path) or not os.path.exists(rule_ninja_path):
        print("❌ 请确保 build.ninja 与 CMakeFiles/rules.ninja 存在")
        return

    rules_dict = parse_rules_ninja(rule_ninja_path)
    build_targets = parse_build_ninja(build_ninja_path)
    enriched_targets = combine_with_rule_commands(build_targets, rules_dict)

    # 保存输出
    output_path = r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\edge_costs\extracted_ninja_targets.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(enriched_targets, f, indent=2, ensure_ascii=False)

    print(f"✅ 提取完毕，共 {len(enriched_targets)} 个构建目标，已保存至 {output_path}")

if __name__ == "__main__":
    main()
