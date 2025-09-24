import re
import json

def parse_variables_from_ninja(file_path):
    """
    解析 ninja 文件里的全局变量定义，返回字典
    仅简单解析 var = value 形式
    """
    var_dict = {}
    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 只简单匹配 var = value
            if '=' in line and not line.startswith('rule'):
                parts = line.split('=', 1)
                var = parts[0].strip()
                val = parts[1].strip()
                var_dict[var] = val
    return var_dict

def parse_rules_from_rule_ninja(file_path):
    """
    解析 rule.ninja 中的 rule 名字和 command 模板，返回 dict {rule_name: command_template}
    """
    rules = {}
    current_rule = None
    with open(file_path, 'r') as f:
        for line in f:
            line_strip = line.strip()
            if line_strip.startswith('rule '):
                current_rule = line_strip[len('rule '):].strip()
            elif current_rule and line_strip.startswith('command ='):
                command = line_strip[len('command ='):].strip()
                rules[current_rule] = command
                current_rule = None  # 一般command后一条即结束
    return rules

def substitute_vars(command_template, var_dict, special_vars):
    """
    递归替换命令模板中的变量
    支持 $VAR 和 ${VAR} 形式
    """
    pattern = re.compile(r'\$(\w+)|\$\{(\w+)\}')
    def repl(m):
        var_name = m.group(1) or m.group(2)
        # 优先用special_vars覆盖
        if var_name in special_vars:
            return special_vars[var_name]
        if var_name in var_dict:
            # 防止死循环，这里简单不递归过深
            val = var_dict[var_name]
            # 再次替换变量
            return substitute_vars(val, var_dict, special_vars)
        return ''
    # 替换直到不变（防止变量互相嵌套无限循环）
    prev_command = None
    current_command = command_template
    max_iter = 10
    iter_count = 0
    while current_command != prev_command and iter_count < max_iter:
        prev_command = current_command
        current_command = pattern.sub(repl, current_command)
        iter_count += 1
    return current_command

def parse_inputs(inputs_list):
    """
    解析inputs字段，分割普通输入和order-only依赖
    返回两个list
    """
    if '||' in inputs_list:
        sep_index = inputs_list.index('||')
        normal_inputs = inputs_list[:sep_index]
        order_only_inputs = inputs_list[sep_index+1:]
    else:
        normal_inputs = inputs_list
        order_only_inputs = []
    return normal_inputs, order_only_inputs

def generate_full_command(task, var_dict, rule_commands):
    """
    根据任务和变量字典，生成完整构建命令
    任务示例结构:
    {
        "outputs": [...],
        "inputs": [...],
        "rule": "rule_name",
        "command_template": "..."
    }
    """
    rule_name = task.get('rule')
    # 如果有规则命令覆盖，优先用rule_ninja里定义的
    if rule_name in rule_commands:
        command_template = rule_commands[rule_name]
    else:
        command_template = task.get('command_template', '')

    # 解析inputs
    inputs = task.get('inputs', [])
    normal_inputs, order_only_inputs = parse_inputs(inputs)

    # special_vars 中包含命令中常用变量
    special_vars = {}

    # - 假设只取第一个输出作为$out
    if task.get('outputs'):
        special_vars['out'] = task['outputs'][0]
    else:
        special_vars['out'] = ''

    # - inputs中所有普通输入路径，以空格连接作为$in
    special_vars['in'] = ' '.join(normal_inputs)

    # - DEP_FILE 这里简单推断为 输出文件.d 文件，实际可以更复杂
    special_vars['DEP_FILE'] = special_vars['out'] + '.d'

    # 递归替换命令模板变量
    full_command = substitute_vars(command_template, var_dict, special_vars)
    return full_command



def load_tasks_from_json(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    return tasks

if __name__ == '__main__':
    # 解析全局变量
    build_ninja_vars = parse_variables_from_ninja(r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\build_optimized\build.ninja")

    # 解析规则命令模板
    rule_cmds = parse_rules_from_rule_ninja(r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\build_optimized\CMakeFiles\rules.ninja")

    # 从json文件加载任务列表
    tasks_json_path = r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\edge_costs\extracted_ninja_targets.json"
    tasks = load_tasks_from_json(tasks_json_path)

    results = []
    for task in tasks:
        full_cmd = generate_full_command(task, build_ninja_vars, rule_cmds)
        results.append({
            "outputs": task.get("outputs", []),
            "inputs": task.get("inputs", []),
            "rule": task.get("rule", ""),
            "full_command": full_cmd
        })

    # 保存结果到json文件
    output_path = r"\\wsl.localhost\Ubuntu\home\enovoleekira\function_test\project\Catch2\edge_costs\full_build_commands.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"共处理 {len(results)} 个任务，结果保存在 {output_path}")
