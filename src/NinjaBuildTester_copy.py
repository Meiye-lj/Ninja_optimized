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
    def __init__(self, root_dir: str, output_file: str, ninja_original: str, ninja_optimized: str, api_key: str, docker_image: str):
        """
        初始化 Ninja 构建测试器

        Args:
            root_dir: 包含项目文件夹的根目录
            output_file: 结果输出的 CSV 文件路径
            ninja_original: 原版 ninja 可执行路径
            ninja_optimized: 优化版 ninja 可执行路径
            api_key: 大模型 API 密钥
            docker_image: 用于执行 LLM 测试的 Docker 镜像
        """
        self.root_dir = root_dir
        self.output_file = output_file
        self.ninja_original = ninja_original
        self.ninja_optimized = ninja_optimized
        self.api_key = api_key
        self.docker_image = docker_image
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
                    "test_source": "N/A",
                    "test_case": "执行失败",
                    "result": f"错误: {str(e)}"
                })

        self.save_results_to_csv()
        logger.info(f"测试完成，结果保存到 {self.output_file}")

    def find_projects(self) -> List[str]:
        """查找所有包含 CMakeLists.txt 的项目"""
        projects = []
        for item in os.listdir(self.root_dir):
            item_path = os.path.join(self.root_dir, item)
            if os.path.isdir(item_path) and any(os.path.exists(os.path.join(item_path, f)) for f in ["CMakeLists.txt"]):
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
            num_jobs = 4
            cmake_cmd = f"cmake -G Ninja -B {build_dir} -S {project_path}"
            build_cmd = f"{ninja_path} -j{num_jobs} -C {build_dir}"

            if subprocess.call(cmake_cmd, shell=True) != 0 or subprocess.call(build_cmd, shell=True) != 0:
                logger.error(f"{project_name} {label} 构建失败")
                self.results.append({
                    "project": project_name,
                    "variant": label,
                    "test_source": "构建",
                    "test_case": "构建",
                    "result": "失败"
                })
                continue

            # 获取 LLM 测试用例
            test_cases_llm = self.get_test_cases_from_llm(project_name)
            llm_success = False

            # 执行 LLM 测试用例（通过 Docker）
            for test_case in test_cases_llm:
                result = self.execute_test_case_in_docker(project_path, test_case)
                self.results.append({
                    "project": project_name,
                    "variant": label,
                    "test_source": "LLM",
                    "test_case": test_case,
                    "result": result
                })
                if "成功" in result:
                    llm_success = True

            # 如果 LLM 测试失败，再尝试本地测试用例
            if not llm_success:
                local_tests = self.find_local_tests(build_dir)
                for test_case in local_tests:
                    result = self.execute_test_case(build_dir, test_case)
                    self.results.append({
                        "project": project_name,
                        "variant": label,
                        "test_source": "Local",
                        "test_case": test_case,
                        "result": result
                    })

    def get_test_cases_from_llm(self, project_name: str) -> List[str]:
        """从大模型获取项目的测试用例"""
        try:
            import openai
            openai.api_key = self.api_key
            openai.base_url = "https://api.deepseek.com/v1/"

            prompt = f"""
            项目名称: {project_name}

            请为该项目生成 1-3 个典型的测试用例。  
            要求：
            1. 每个测试用例必须是一个可直接执行的命令行指令。  
            2. 这些命令将在 Docker 容器中通过以下方式执行：  
            docker run --rm docker_tag test_case  
            其中 test_case 即为你提供的命令。  
            3. 输出格式必须是一个 JSON 数组，数组元素均为字符串。  
            4. 不要输出说明文字、注释或多余内容，只返回 JSON 数组。  
            5. 不要使用 --version 或类似无效的检查指令，请尽量选择能验证功能正确性的命令。  

            输出示例（注意格式）：  
            ["./configure && make test", "make check", "python3 -m unittest tests/test_module.py"]
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

    def execute_test_case_in_docker(self, project_path: str, test_case: str) -> str:
        """通过 Docker 执行测试用例"""
        try:
            abs_path = os.path.abspath(project_path)
            cmd = f"docker run --rm -v {abs_path}:/project {self.docker_image} /bin/bash -c 'cd /project && {test_case}'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                return f"成功: {result.stdout.strip()}"
            else:
                return f"失败: 返回码 {result.returncode}, 错误: {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return "失败: 测试超时(5分钟)"
        except Exception as e:
            return f"失败: 执行测试出错: {str(e)}"

    def find_local_tests(self, build_dir: str) -> List[str]:
        """查找本地测试用例"""
        tests = []
        # 默认查找 ctest 或 make test
        if os.path.exists(os.path.join(build_dir, "Makefile")):
            tests.append("make test")
        elif os.path.exists(build_dir):
            tests.append("ctest -j4")
        return tests

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
        """保存测试结果到 CSV"""
        try:
            with open(self.output_file, "w", newline="", encoding="utf-8-sig") as csvfile:
                fieldnames = ["项目名", "构建版本", "测试来源", "测试用例", "测试结果"]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for result in self.results:
                    writer.writerow({
                        "项目名": result["project"],
                        "构建版本": result["variant"],
                        "测试来源": result["test_source"],
                        "测试用例": result["test_case"],
                        "测试结果": result["result"]
                    })
        except Exception as e:
            logger.error(f"保存结果到 CSV 失败: {str(e)}")


if __name__ == "__main__":
    import os

    ROOT_DIR = "project/googletest"
    OUTPUT_FILE = "ninja_build_test_results.csv"
    NINJA_ORIGINAL = "ninja-original/ninja"
    NINJA_OPTIMIZED = "ninja-optimized/ninja"
    API_KEY = "sk-c86d12a711e4446a96977d869a45be4e"
    DOCKER_IMAGE = "my_project_test:latest"

    if not os.path.exists(ROOT_DIR):
        print(f"错误: 根目录 {ROOT_DIR} 不存在")
        exit(1)
    if not API_KEY:
        print("错误: 请设置 Deepseek API Key")
        exit(1)

    tester = NinjaBuildTester(
        root_dir=ROOT_DIR,
        output_file=OUTPUT_FILE,
        ninja_original=NINJA_ORIGINAL,
        ninja_optimized=NINJA_OPTIMIZED,
        api_key=API_KEY,
        docker_image=DOCKER_IMAGE
    )
    tester.run()
