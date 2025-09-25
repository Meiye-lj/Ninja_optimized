import os
import subprocess
import csv
import re
import json
import time
import logging
from typing import List, Dict, Tuple, Optional, Any

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DockerImageTester:
    def __init__(self, root_dir: str, output_file: str, api_key: str):
        """
        初始化Docker镜像测试器
        
        Args:
            root_dir: 包含项目文件夹的根目录
            output_file: 结果输出的CSV文件路径
            api_key: Deepseek API密钥
        """
        self.root_dir = root_dir
        self.output_file = output_file
        self.api_key = api_key
        self.results = []

    def run(self) -> None:
        """运行测试流程"""
        # 步骤1: 查找所有包含Dockerfile的项目
        projects = self.find_projects_with_dockerfile()
        logger.info(f"找到 {len(projects)} 个包含Dockerfile的项目")
        
        # 步骤2: 依次测试每个项目
        for project in projects:
            try:
                self.test_project(project)
            except Exception as e:
                logger.error(f"测试项目 {project} 时出错: {str(e)}")
                self.results.append({
                    "project": project,
                    "test_case": "测试执行失败",
                    "result": f"错误: {str(e)}"
                })
        
        # 步骤3: 保存结果到CSV
        self.save_results_to_csv()
        logger.info(f"测试完成，结果已保存到 {self.output_file}")

    def find_projects_with_dockerfile(self) -> List[str]:
        """查找所有包含Dockerfile的项目文件夹"""
        projects = []
        for item in os.listdir(self.root_dir):
            item_path = os.path.join(self.root_dir, item)
            if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "Dockerfile")):
                projects.append(item)
        return projects

    def test_project(self, project_name: str) -> None:
        """测试单个项目
        
        Args:
            project_name: 项目名称
        """
        logger.info(f"开始测试项目: {project_name}")
        docker_tag = project_name.lower()
        
        # 获取测试用例
        test_cases = self.get_test_cases_from_deepseek(project_name)
        if not test_cases:
            logger.warning(f"未能获取项目 {project_name} 的测试用例")
            self.results.append({
                "project": project_name,
                "test_case": "获取测试用例失败",
                "result": "未能从Deepseek获取测试用例"
            })
            return
        
        # 执行每个测试用例
        for test_case in test_cases:
            result = self.execute_test_case(docker_tag, test_case)
            self.results.append({
                "project": project_name,
                "test_case": test_case,
                "result": result
            })

    def get_test_cases_from_deepseek(self, project_name: str) -> List[str]:
        """从Deepseek获取项目的测试用例
        
        Args:
            project_name: 项目名称
        
        Returns:
            测试用例列表
        """
        try:
            import openai
            openai.api_key = self.api_key
            openai.base_url="https://api.deepseek.com/v1/"
            # openai.
            # 构建提示
            prompt = f"""
            项目名称: {project_name}
            
            请为这个项目提供1个典型的测试用例。每个测试用例应该是一个可以在Docker容器中执行的命令。
            我将要执行的测试指令"docker run --rm docker_tag test_case"。
            请考虑我的测试指令并以列表形式返回这些测试用例，不考虑使用--vsrsion，不要给出说明和其他文字，例如:
            ["用例1"]
            """
            
            # 调用Deepseek API
            response = openai.chat.completions.create(
                model="deepseek-reasoner",
                messages=[{"role": "user", "content": prompt}]
            )
            
            # 解析响应
            response_text = response.choices[0].message.content
            logger.debug(f"Deepseek响应: {response_text}")
            
            # 尝试解析为JSON数组
            try:
                test_cases = json.loads(response_text)
                if isinstance(test_cases, list) and all(isinstance(tc, str) for tc in test_cases):
                    return test_cases
            except json.JSONDecodeError:
                pass
            
            # 如果无法解析为JSON，尝试从文本中提取命令
            test_cases = []
            lines = response_text.strip().split('\n')
            for line in lines:
                # 简单提取可能的命令行
                if line.startswith('["') or line.startswith('"') or line.startswith("'"):
                    continue
                line = line.strip()
                if line and not line.startswith('#'):
                    test_cases.append(line)
            
            return test_cases[:3]  # 限制为最多3个测试用例
            
        except Exception as e:
            logger.error(f"调用Deepseek API失败: {str(e)}")
            return []

    def execute_test_case(self, docker_tag: str, test_case: str) -> str:
        """在Docker镜像中执行测试用例
        
        Args:
            docker_tag: Docker镜像标签
            test_case: 测试用例命令
        
        Returns:
            测试结果
        """
        try:
            # 构建并执行Docker命令
            docker_cmd = f"docker run --rm {docker_tag} {test_case}"
            result = subprocess.run(
                docker_cmd, 
                shell=True, 
                capture_output=True, 
                text=True,
                timeout=300  # 设置超时时间为5分钟
            )
            
            # 检查返回码
            if result.returncode == 0:
                return f"成功: {result.stdout.strip()}"
            else:
                return f"失败: 返回码 {result.returncode}, 错误: {result.stderr.strip()}"
                
        except subprocess.TimeoutExpired:
            return "失败: 测试超时(5分钟)"
        except Exception as e:
            return f"失败: 执行测试时出错: {str(e)}"

    def save_results_to_csv(self) -> None:
        """将测试结果保存到CSV文件"""
        try:
            with open(self.output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = ['项目名', '测试用例', '测试结果']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for result in self.results:
                    writer.writerow({
                        '项目名': result['project'],
                        '测试用例': result['test_case'],
                        '测试结果': result['result']
                    })
        except Exception as e:
            logger.error(f"保存结果到CSV失败: {str(e)}")

if __name__ == "__main__":
    # 配置参数
    ROOT_DIR = "/home/lyujun/Dockerspace" 
    OUTPUT_FILE = "docker_image_test_results.csv"
    API_KEY = 'sk-c86d12a711e4446a96977d869a45be4e'
    
    if not API_KEY:
        print("错误: 请设置DEEPSEEK_API_KEY环境变量")
        exit(1)
    
    # 创建并运行测试器
    tester = DockerImageTester(ROOT_DIR, OUTPUT_FILE, API_KEY)
    tester.run()    