import os
import subprocess
import csv
import json
import logging
from typing import List, Dict

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class NinjaBuildTester:
    def __init__(self, root_dir: str, output_file: str, ninja_original: str, ninja_optimized: str, api_key: str):
        """
        初始化Ninja构建测试器

        Args:
            root_dir: 包含项目文件夹的根目录
            output_file: 结果输出的CSV文件路径
            ninja_original: 原版ninja可执行路径
            ninja_optimized: 优化版ninja可执行路径
            api_key: 大模型API密钥
        """
        self.root_dir = root_dir
        self.output_file = output_file
        self.ninja_original = ninja_original
        self.ninja_optimized = ninja_optimized
        self.api_key = api_key
        self.results: List[Dict] = []

    def run(self) -> None:
        """运行测试流程"""
        projects = self.find_projects()
        logger.info(f"找到 {len(projects)} 个项目")

        for project in projects:
            try:
                self.test_project(project)
            except Exception as e:
                logger.error(f"测试项目 {project} 出错: {str(e)}")
                self.results.append({
                    "project": project,
                    "variant": "N/A",
                    "test_case": "执行失败",
                    "result": f"错误: {str(e)}"
                })

        self.save_results_to_csv()
        logger.info(f"测试完成，结果保存到 {self.output_file}")

    def find_projects(self) -> List[str]:
        """查找所有包含CMakeLists.txt的项目"""
        projects = []
        for item in os.listdir(self.root_dir):
            item_path = os.path.join(self.root_dir, item)
            if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "CMakeLists.txt")):
                projects.append(item)
        return projects

    def test_project(self, project_name: str) -> None:
        """测试单个项目"""
        project_path = os.path.join(self.root_dir, project_name)
        logger.info(f"开始测试项目: {project_name}")

        for label, ninja_path in [("original", self.ninja_original), ("optimized", self.ninja_optimized)]:
            build_dir = os.path.join(project_path, f"build_{label}")
            os.makedirs(build_dir, exist_ok=True)

            # 配置 + 构建
            cmake_cmd = f"cmake -G Ninja -B {build_dir} -S {project_path}"
            build_cmd = f"{ninja_path} -C {build_dir}"

            if subprocess.call(cmake_cmd, shell=True) != 0 or subprocess.call(build_cmd, shell=True) != 0:
                logger.error(f"{project_name} {label} 构建失败")
                self.results.append({
                    "project": project_name,
                    "variant": label,
                    "test_case": "构建",
                    "result": "失败"
                })
                continue

            # 获取测试用例
            test_cases = self.get_test_cases_from_llm(project_name)
            if not test_cases:
                self.results.append({
                    "project": project_name,
                    "variant": label,
                    "test_case": "获取测试用例",
                    "result": "失败"
                })
                continue

            # 执行测试
            for test_case in test_cases:
                result = self.execute_test_case(build_dir, test_case)
                self.results.append({
                    "project": project_name,
                    "variant": label,
                    "test_case": test_case,
                    "result": result
                })

    def get_test_cases_from_llm(self, project_name: str) -> List[str]:
        """从大模型获取项目的测试命令"""
        try:
            import openai
            openai.api_key = self.api_key
            openai.base_url = "https://api.deepseek.com/v1/"

            prompt = f"""
            你是一个资深的软件测试工程师。
            项目名称: {project_name}

            请为该项目生成**可直接运行的shell测试命令**，要求：
            1. 命令在Linux下可直接执行。
            2. 尽量选择常见的测试框架命令（如 ctest, make test, pytest 等）。
            3. 不要生成无效命令，不要使用 --version。
            4. 输出 JSON 数组，每个元素是字符串，例如：
               ["ctest -j4", "make test", "pytest -q tests/"]
            """

            response = openai.chat.completions.create(
                model="deepseek-reasoner",
                messages=[{"role": "user", "content": prompt}]
            )
            response_text = response.choices[0].message.content.strip()

            try:
                test_cases = json.loads(response_text)
                if isinstance(test_cases, list) and all(isinstance(tc, str) for tc in test_cases):
                    return test_cases
            except json.JSONDecodeError:
                pass

            return []
        except Exception as e:
            logger.error(f"调用大模型失败: {str(e)}")
            return []

    def execute_test_case(self, cwd: str, test_case: str) -> str:
        """在指定目录中执行测试用例"""
        try:
            result = subprocess.run(
                test_case,
                cwd=cwd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                return f"成功: {result.stdout.strip()}"
            else:
                return f"失败: 返回码 {result.returncode}, 错误: {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return "失败: 测试超时(5分钟)"
        except Exception as e:
            return f"失败: 执行测试出错: {str(e)}"

    def save_results_to_csv(self) -> None:
        """保存测试结果到CSV"""
        try:
            with open(self.output_file, "w", newline="", encoding="utf-8-sig") as csvfile:
                fieldnames = ["项目名", "构建版本", "测试用例", "测试结果"]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for result in self.results:
                    writer.writerow({
                        "项目名": result["project"],
                        "构建版本": result["variant"],
                        "测试用例": result["test_case"],
                        "测试结果": result["result"]
                    })
        except Exception as e:
            logger.error(f"保存结果到CSV失败: {str(e)}")

if __name__ == "__main__":
    import os

    # 配置参数
    ROOT_DIR = "project"  # 你的项目根目录
    OUTPUT_FILE = "ninja_build_test_results.csv"
    NINJA_ORIGINAL = "ninja-original/ninja"   # 原版 ninja 可执行路径
    NINJA_OPTIMIZED = "ninja-optimized/ninja"  # 优化版 ninja 可执行路径
    API_KEY = "sk-c86d12a711e4446a96977d869a45be4e"  # 大模型 API Key

    if not os.path.exists(ROOT_DIR):
        print(f"错误: 根目录 {ROOT_DIR} 不存在")
        exit(1)

    if not API_KEY:
        print("错误: 请设置 Deepseek API Key")
        exit(1)

    # 创建测试器并运行
    tester = NinjaBuildTester(
        root_dir=ROOT_DIR,
        output_file=OUTPUT_FILE,
        ninja_original=NINJA_ORIGINAL,
        ninja_optimized=NINJA_OPTIMIZED,
        api_key=API_KEY
    )

    tester.run()

