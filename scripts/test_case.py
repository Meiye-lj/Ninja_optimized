import json
import subprocess
import logging
from typing import List
import openai
import os

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Deepseek API Key
API_KEY = "sk-c86d12a711e4446a96977d869a45be4e"

# 项目可执行文件映射
PROJECT_EXEC_MAP = {
    "json-c": "/home/enovoleekira/function_test/project/json-c/build_optimized/json_parse",
    "googletest": "/home/enovoleekira/function_test/project/googletest/build_optimized/test",
    "cxxopts": "/home/enovoleekira/function_test/project/cxxopts/build_optimized/example",
    "Catch2": "/home/enovoleekira/function_test/project/Catch2/build_optimized/test",
    "fmt": "fmt",  # 系统命令，保持原样
}

# 输出结果目录
RESULT_DIR = "/home/enovoleekira/function_test/result/project_tests"
os.makedirs(RESULT_DIR, exist_ok=True)

class ProjectTester:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_test_cases_from_deepseek(self, project_name: str) -> List[str]:
        """从Deepseek获取项目测试用例"""
        try:
            openai.api_key = self.api_key
            openai.base_url = "https://api.deepseek.com/v1/"

            prompt = f"""
            项目名称: {project_name}
            
            请为这个项目提供3个典型的测试用例。每个测试用例应该是可以直接在Linux shell中执行的命令。
            不需要--version，直接给出命令列表，例如:
            ["用例1", "用例2", "用例3"]
            """

            response = openai.chat.completions.create(
                model="deepseek-reasoner",
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.choices[0].message.content
            logger.info(f"Deepseek响应: {response_text}")

            # 尝试解析为JSON
            try:
                test_cases = json.loads(response_text)
                if isinstance(test_cases, list) and all(isinstance(tc, str) for tc in test_cases):
                    return test_cases[:3]
            except json.JSONDecodeError:
                pass

            # 简单文本解析
            lines = response_text.strip().split('\n')
            test_cases = [line.strip() for line in lines if line.strip()]
            return test_cases[:3]

        except Exception as e:
            logger.error(f"调用Deepseek API失败: {str(e)}")
            return []

    def run_test_case(self, project_name: str, test_case: str) -> bool:
        """执行单个测试用例"""
        exec_path = PROJECT_EXEC_MAP.get(project_name, "")
        # 如果是Deepseek返回的占位命令，替换为实际可执行文件路径
        if exec_path and test_case.startswith("./") or test_case.split()[0] in ["json_parse", "example", "test"]:
            test_case = test_case.replace(test_case.split()[0], exec_path, 1)

        try:
            result = subprocess.run(test_case, shell=True, capture_output=True, timeout=10, text=True)
            if result.returncode == 0:
                return True
            else:
                logger.warning(f"测试失败: {test_case}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
                return False
        except Exception as e:
            logger.warning(f"执行测试失败: {test_case} 错误: {e}")
            return False

    def test_project(self, project_name: str):
        logger.info(f"\n=== 开始测试项目: {project_name} ===")
        test_cases = self.get_test_cases_from_deepseek(project_name)
        logger.info(f"获取到 {len(test_cases)} 个测试用例")

        results = []
        for idx, case in enumerate(test_cases, 1):
            success = self.run_test_case(project_name, case)
            results.append((case, "成功" if success else "失败"))
            logger.info(f"测试用例 {idx}: {'成功' if success else '失败'}")

        # 保存结果
        output_file = os.path.join(RESULT_DIR, f"{project_name}_test_result.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"=== {project_name} 测试结果 ===\n")
            for case, status in results:
                f.write(f"{case}: {status}\n")

        logger.info(f"测试结果保存至 {output_file}")

if __name__ == "__main__":
    tester = ProjectTester(API_KEY)
    projects = ["json-c", "googletest", "fmt", "cxxopts", "Catch2"]
    for proj in projects:
        tester.test_project(proj)
