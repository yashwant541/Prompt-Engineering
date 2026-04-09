from flask import Flask, request, render_template, jsonify
from flask_cors import CORS
import ast
import inspect
import tempfile
import os
from pathlib import Path
from collections import defaultdict, deque
import difflib

app = Flask(__name__)
CORS(app)

class DependencyAnalyzer:
    """Analyzes function dependencies and call hierarchy"""
    
    def __init__(self, tree, code_string):
        self.tree = tree
        self.code_string = code_string
        self.function_calls = defaultdict(set)
        self.call_graph = {}
        self.process_flow = []
        
    def analyze_dependencies(self):
        """Build dependency graph between functions"""
        functions = {}
        
        # First pass: collect all function definitions
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = node
        
        # Second pass: analyze calls within each function
        for func_name, func_node in functions.items():
            calls = set()
            for child in ast.walk(func_node):
                if isinstance(child, ast.Call):
                    # Get the called function name
                    if isinstance(child.func, ast.Name):
                        calls.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls.add(child.func.attr)
            
            self.function_calls[func_name] = calls
            self.call_graph[func_name] = {
                'calls': list(calls),
                'called_by': [],
                'line_count': self._get_function_lines(func_node),
                'start_line': func_node.lineno,
                'end_line': func_node.end_lineno if hasattr(func_node, 'end_lineno') else func_node.lineno
            }
        
        # Build reverse dependencies (who calls this function)
        for func_name, deps in self.function_calls.items():
            for called_func in deps:
                if called_func in self.call_graph:
                    self.call_graph[called_func]['called_by'].append(func_name)
        
        return self.call_graph
    
    def _get_function_lines(self, func_node):
        """Get line count for a function"""
        if hasattr(func_node, 'body') and func_node.body:
            first_line = func_node.lineno
            last_line = func_node.end_lineno if hasattr(func_node, 'end_lineno') else func_node.body[-1].lineno
            return last_line - first_line + 1
        return 0
    
    def get_execution_flow(self, entry_point=None):
        """Get the process flow/path of execution"""
        if not self.call_graph:
            self.analyze_dependencies()
        
        # If no entry point specified, find functions with no dependencies (leaf functions)
        if not entry_point:
            # Find root functions (functions that don't call others or are main)
            entry_points = []
            for func_name, details in self.call_graph.items():
                if not details['calls'] or func_name.lower() in ['main', 'run', 'execute', 'process']:
                    entry_points.append(func_name)
            
            if not entry_points and self.call_graph:
                entry_points = [list(self.call_graph.keys())[0]]
        else:
            entry_points = [entry_point]
        
        # Build process flow using BFS/DFS
        flow = []
        visited = set()
        
        for entry in entry_points:
            if entry in self.call_graph:
                flow.append(self._trace_flow(entry, visited, 0))
        
        return flow
    
    def _trace_flow(self, func_name, visited, depth):
        """Recursively trace function call flow"""
        if func_name in visited:
            return {
                'name': func_name,
                'depth': depth,
                'cycle': True,
                'calls': []
            }
        
        visited.add(func_name)
        
        flow_node = {
            'name': func_name,
            'depth': depth,
            'line_count': self.call_graph.get(func_name, {}).get('line_count', 0),
            'start_line': self.call_graph.get(func_name, {}).get('start_line', 0),
            'end_line': self.call_graph.get(func_name, {}).get('end_line', 0),
            'calls': []
        }
        
        if func_name in self.call_graph:
            for called_func in self.call_graph[func_name]['calls']:
                if called_func in self.call_graph:
                    flow_node['calls'].append(
                        self._trace_flow(called_func, visited.copy(), depth + 1)
                    )
        
        return flow_node
    
    def get_dependency_summary(self):
        """Get summary of dependencies including open/unresolved dependencies"""
        if not self.call_graph:
            self.analyze_dependencies()
        
        summary = {
            'total_functions': len(self.call_graph),
            'functions_with_dependencies': 0,
            'open_dependencies': [],
            'dependency_depth': {},
            'circular_dependencies': []
        }
        
        # Find open dependencies (calls to functions not defined in the code)
        for func_name, details in self.call_graph.items():
            if details['calls']:
                summary['functions_with_dependencies'] += 1
                
            for called_func in details['calls']:
                if called_func not in self.call_graph:
                    # This is an external/open dependency
                    summary['open_dependencies'].append({
                        'caller': func_name,
                        'dependency': called_func,
                        'line': details['start_line']
                    })
        
        # Calculate dependency depth
        for func_name in self.call_graph:
            depth = self._calculate_depth(func_name, set())
            summary['dependency_depth'][func_name] = depth
        
        # Detect circular dependencies
        summary['circular_dependencies'] = self._detect_circular_dependencies()
        
        return summary
    
    def _calculate_depth(self, func_name, visited):
        """Calculate maximum call depth for a function"""
        if func_name not in self.call_graph:
            return 0
        
        if func_name in visited:
            return 0  # Circular reference
        
        visited.add(func_name)
        max_depth = 0
        
        for called_func in self.call_graph[func_name]['calls']:
            if called_func in self.call_graph:
                depth = self._calculate_depth(called_func, visited)
                max_depth = max(max_depth, depth + 1)
        
        return max_depth
    
    def _detect_circular_dependencies(self):
        """Detect circular dependencies in function calls"""
        circular = []
        visited = set()
        rec_stack = set()
        
        def detect_cycle(func_name, path):
            if func_name in rec_stack:
                # Found a cycle
                cycle_start = path.index(func_name)
                circular.append(path[cycle_start:] + [func_name])
                return True
            
            if func_name in visited or func_name not in self.call_graph:
                return False
            
            visited.add(func_name)
            rec_stack.add(func_name)
            path.append(func_name)
            
            for called_func in self.call_graph[func_name]['calls']:
                if called_func in self.call_graph:
                    detect_cycle(called_func, path)
            
            path.pop()
            rec_stack.remove(func_name)
            return False
        
        for func_name in self.call_graph:
            if func_name not in visited:
                detect_cycle(func_name, [])
        
        return circular

class CodeAnalyzer:
    def __init__(self, code_string=None, file_path=None):
        self.code_string = code_string
        self.file_path = file_path
        self.tree = None
        self.functions = []
        self.dependency_analyzer = None
        
    def parse_code(self):
        """Parse the Python code into AST"""
        try:
            if self.file_path:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self.code_string = f.read()
            self.tree = ast.parse(self.code_string)
            return True
        except SyntaxError as e:
            return str(e)
        except Exception as e:
            return str(e)
    
    def extract_functions(self):
        """Extract all functions with their line counts and details"""
        if not self.tree:
            return []
        
        functions = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                # Count lines in function body
                if hasattr(node, 'body') and node.body:
                    first_line = node.lineno
                    last_line = node.end_lineno if hasattr(node, 'end_lineno') else node.body[-1].lineno
                    line_count = last_line - first_line + 1
                else:
                    line_count = 0
                
                functions.append({
                    'name': node.name,
                    'start_line': node.lineno,
                    'end_line': node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
                    'line_count': line_count,
                    'args': [arg.arg for arg in node.args.args],
                    'decorators': [self._get_decorator_name(d) for d in node.decorator_list]
                })
        
        self.functions = functions
        return functions
    
    def _get_decorator_name(self, decorator):
        """Extract decorator name from AST node"""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr
        return str(decorator)
    
    def get_code_structure(self):
        """Get complete code structure with line counts"""
        if not self.tree:
            return None
        
        total_lines = len(self.code_string.splitlines())
        
        structure = {
            'total_lines': total_lines,
            'functions': self.functions,
            'classes': self._extract_classes(),
            'imports': self._extract_imports(),
            'global_code_lines': 0
        }
        
        # Calculate global code lines (outside functions/classes)
        used_lines = set()
        for func in self.functions:
            for line in range(func['start_line'], func['end_line'] + 1):
                used_lines.add(line)
        
        for cls in structure['classes']:
            for line in range(cls['start_line'], cls['end_line'] + 1):
                used_lines.add(line)
        
        structure['global_code_lines'] = total_lines - len(used_lines)
        
        # Analyze dependencies
        if self.tree:
            self.dependency_analyzer = DependencyAnalyzer(self.tree, self.code_string)
            structure['dependencies'] = self.dependency_analyzer.get_dependency_summary()
            structure['process_flow'] = self.dependency_analyzer.get_execution_flow()
            structure['call_graph'] = self.dependency_analyzer.call_graph
        
        return structure
    
    def _extract_classes(self):
        """Extract classes from the code"""
        classes = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                first_line = node.lineno
                last_line = node.end_lineno if hasattr(node, 'end_lineno') else node.body[-1].lineno
                line_count = last_line - first_line + 1
                
                methods = []
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        methods.append({
                            'name': item.name,
                            'line_count': item.end_lineno - item.lineno + 1 if hasattr(item, 'end_lineno') else 1
                        })
                
                classes.append({
                    'name': node.name,
                    'start_line': node.lineno,
                    'end_line': node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
                    'line_count': line_count,
                    'methods': methods
                })
        return classes
    
    def _extract_imports(self):
        """Extract all imports from the code"""
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module if node.module else ''
                for alias in node.names:
                    imports.append(f"from {module} import {alias.name}")
        return imports

class CodeComparator:
    def __init__(self, code1_structure, code2_structure):
        self.code1 = code1_structure
        self.code2 = code2_structure
        
    def compare(self):
        """Compare two code structures and identify differences"""
        differences = {
            'total_lines': {
                'code1': self.code1['total_lines'],
                'code2': self.code2['total_lines'],
                'difference': self.code2['total_lines'] - self.code1['total_lines']
            },
            'functions_added': [],
            'functions_removed': [],
            'functions_modified': [],
            'classes_added': [],
            'classes_removed': [],
            'classes_modified': [],
            'imports_added': [],
            'imports_removed': [],
            'dependencies_added': [],
            'dependencies_removed': [],
            'process_flow_changes': []
        }
        
        # Compare functions
        funcs1 = {f['name']: f for f in self.code1['functions']}
        funcs2 = {f['name']: f for f in self.code2['functions']}
        
        # Added functions
        for name in funcs2:
            if name not in funcs1:
                differences['functions_added'].append(funcs2[name])
        
        # Removed functions
        for name in funcs1:
            if name not in funcs2:
                differences['functions_removed'].append(funcs1[name])
        
        # Modified functions
        for name in funcs1:
            if name in funcs2:
                if funcs1[name]['line_count'] != funcs2[name]['line_count']:
                    differences['functions_modified'].append({
                        'name': name,
                        'old_lines': funcs1[name]['line_count'],
                        'new_lines': funcs2[name]['line_count'],
                        'difference': funcs2[name]['line_count'] - funcs1[name]['line_count']
                    })
        
        # Compare classes
        classes1 = {c['name']: c for c in self.code1['classes']}
        classes2 = {c['name']: c for c in self.code2['classes']}
        
        for name in classes2:
            if name not in classes1:
                differences['classes_added'].append(classes2[name])
        
        for name in classes1:
            if name not in classes2:
                differences['classes_removed'].append(classes1[name])
        
        for name in classes1:
            if name in classes2:
                if classes1[name]['line_count'] != classes2[name]['line_count']:
                    differences['classes_modified'].append({
                        'name': name,
                        'old_lines': classes1[name]['line_count'],
                        'new_lines': classes2[name]['line_count'],
                        'difference': classes2[name]['line_count'] - classes1[name]['line_count']
                    })
        
        # Compare imports
        imports1 = set(self.code1['imports'])
        imports2 = set(self.code2['imports'])
        
        differences['imports_added'] = list(imports2 - imports1)
        differences['imports_removed'] = list(imports1 - imports2)
        
        # Compare dependencies
        if 'dependencies' in self.code1 and 'dependencies' in self.code2:
            deps1 = set([f"{d['caller']}->{d['dependency']}" for d in self.code1['dependencies'].get('open_dependencies', [])])
            deps2 = set([f"{d['caller']}->{d['dependency']}" for d in self.code2['dependencies'].get('open_dependencies', [])])
            
            differences['dependencies_added'] = list(deps2 - deps1)
            differences['dependencies_removed'] = list(deps1 - deps2)
        
        return differences

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    """Analyze a single Python code file"""
    try:
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
            
            # Save temporary file
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, file.filename)
            file.save(temp_path)
            
            analyzer = CodeAnalyzer(file_path=temp_path)
            parse_result = analyzer.parse_code()
            
            if parse_result is not True:
                return jsonify({'error': f'Parse error: {parse_result}'}), 400
            
            analyzer.extract_functions()
            structure = analyzer.get_code_structure()
            
            # Clean up
            os.remove(temp_path)
            
            return jsonify({
                'success': True,
                'structure': structure,
                'code': analyzer.code_string
            })
        
        elif 'code' in request.form:
            code_string = request.form['code']
            analyzer = CodeAnalyzer(code_string=code_string)
            parse_result = analyzer.parse_code()
            
            if parse_result is not True:
                return jsonify({'error': f'Parse error: {parse_result}'}), 400
            
            analyzer.extract_functions()
            structure = analyzer.get_code_structure()
            
            return jsonify({
                'success': True,
                'structure': structure,
                'code': code_string
            })
        
        return jsonify({'error': 'No file or code provided'}), 400
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/compare', methods=['POST'])
def compare():
    """Compare two Python code files"""
    try:
        data = request.json
        code1 = data.get('code1')
        code2 = data.get('code2')
        
        if not code1 or not code2:
            return jsonify({'error': 'Both code snippets are required'}), 400
        
        # Analyze first code
        analyzer1 = CodeAnalyzer(code_string=code1)
        parse_result1 = analyzer1.parse_code()
        if parse_result1 is not True:
            return jsonify({'error': f'Parse error in first code: {parse_result1}'}), 400
        
        analyzer1.extract_functions()
        structure1 = analyzer1.get_code_structure()
        
        # Analyze second code
        analyzer2 = CodeAnalyzer(code_string=code2)
        parse_result2 = analyzer2.parse_code()
        if parse_result2 is not True:
            return jsonify({'error': f'Parse error in second code: {parse_result2}'}), 400
        
        analyzer2.extract_functions()
        structure2 = analyzer2.get_code_structure()
        
        # Compare
        comparator = CodeComparator(structure1, structure2)
        differences = comparator.compare()
        
        return jsonify({
            'success': True,
            'code1_structure': structure1,
            'code2_structure': structure2,
            'differences': differences
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/revert-function', methods=['POST'])
def revert_function():
    """Revert a specific function to its original version"""
    try:
        data = request.json
        original_code = data.get('original_code')
        current_code = data.get('current_code')
        function_name = data.get('function_name')
        
        if not all([original_code, current_code, function_name]):
            return jsonify({'error': 'Missing required parameters'}), 400
        
        # Parse both code versions
        analyzer_original = CodeAnalyzer(code_string=original_code)
        parse_result = analyzer_original.parse_code()
        if parse_result is not True:
            return jsonify({'error': f'Error parsing original code: {parse_result}'}), 400
        
        analyzer_current = CodeAnalyzer(code_string=current_code)
        parse_result = analyzer_current.parse_code()
        if parse_result is not True:
            return jsonify({'error': f'Error parsing current code: {parse_result}'}), 400
        
        # Extract the specific function from original code
        original_function = extract_function_by_name(analyzer_original.tree, function_name)
        if not original_function:
            return jsonify({'error': f'Function "{function_name}" not found in original code'}), 400
        
        # Extract the function from current code to verify it exists
        current_function = extract_function_by_name(analyzer_current.tree, function_name)
        if not current_function:
            return jsonify({'error': f'Function "{function_name}" not found in current code'}), 400
        
        # Replace the function in current code
        updated_code = replace_function_in_code(current_code, original_function, function_name)
        
        return jsonify({
            'success': True,
            'updated_code': updated_code,
            'function_name': function_name,
            'message': f'Successfully reverted {function_name}() to original version'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/revert-all-functions', methods=['POST'])
def revert_all_functions():
    """Revert all modified functions to their original versions"""
    try:
        data = request.json
        original_code = data.get('original_code')
        current_code = data.get('current_code')
        modified_functions = data.get('modified_functions', [])
        
        if not all([original_code, current_code]):
            return jsonify({'error': 'Missing required parameters'}), 400
        
        updated_code = current_code
        
        for func_name in modified_functions:
            # Parse original code to get the function
            analyzer_original = CodeAnalyzer(code_string=original_code)
            analyzer_original.parse_code()
            
            original_function = extract_function_by_name(analyzer_original.tree, func_name)
            if original_function:
                updated_code = replace_function_in_code(updated_code, original_function, func_name)
        
        return jsonify({
            'success': True,
            'updated_code': updated_code,
            'message': f'Successfully reverted {len(modified_functions)} function(s)'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get-function-diff', methods=['POST'])
def get_function_diff():
    """Get detailed diff for a specific function"""
    try:
        data = request.json
        original_code = data.get('original_code')
        current_code = data.get('current_code')
        function_name = data.get('function_name')
        
        if not all([original_code, current_code, function_name]):
            return jsonify({'error': 'Missing required parameters'}), 400
        
        # Extract both versions of the function
        analyzer_original = CodeAnalyzer(code_string=original_code)
        analyzer_original.parse_code()
        
        analyzer_current = CodeAnalyzer(code_string=current_code)
        analyzer_current.parse_code()
        
        original_func = extract_function_by_name(analyzer_original.tree, function_name)
        current_func = extract_function_by_name(analyzer_current.tree, function_name)
        
        if not original_func or not current_func:
            return jsonify({'error': 'Function not found in one or both versions'}), 400
        
        # Extract the actual code
        original_lines = original_code.splitlines()[original_func['start_line']-1:original_func['end_line']]
        current_lines = current_code.splitlines()[current_func['start_line']-1:current_func['end_line']]
        
        # Simple diff calculation
        diff = list(difflib.unified_diff(
            original_lines,
            current_lines,
            fromfile=f'Original {function_name}()',
            tofile=f'Current {function_name}()',
            lineterm=''
        ))
        
        return jsonify({
            'success': True,
            'original_code': '\n'.join(original_lines),
            'current_code': '\n'.join(current_lines),
            'diff': diff,
            'function_name': function_name
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def extract_function_by_name(tree, function_name):
    """Extract a function node by name from AST"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            # Get the source code for this function
            start_line = node.lineno
            end_line = node.end_lineno if hasattr(node, 'end_lineno') else node.body[-1].lineno
            
            # Extract the source lines
            return {
                'name': node.name,
                'start_line': start_line,
                'end_line': end_line,
                'args': [arg.arg for arg in node.args.args],
                'decorators': node.decorator_list
            }
    return None

def replace_function_in_code(code, function_info, function_name):
    """Replace a function in the code string"""
    lines = code.splitlines(keepends=True)
    
    # Find the function in current code
    start_idx = None
    end_idx = None
    indent_level = None
    
    for i, line in enumerate(lines):
        # Look for function definition
        if line.strip().startswith(f'def {function_name}('):
            start_idx = i
            # Calculate indent level
            indent_level = len(line) - len(line.lstrip())
            break
    
    if start_idx is None:
        return code
    
    # Find where the function ends (by tracking indentation)
    for i in range(start_idx + 1, len(lines)):
        if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= indent_level:
            if not lines[i].strip().startswith('@'):  # Skip decorators
                end_idx = i
                break
    
    if end_idx is None:
        end_idx = len(lines)
    
    # Extract original function from original code
    original_lines = []
    temp_analyzer = CodeAnalyzer(code_string=code)
    temp_analyzer.parse_code()
    
    # Find original function in a separate parse
    for node in ast.walk(temp_analyzer.tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, 'end_lineno') else node.body[-1].lineno
            original_lines = code.splitlines(keepends=True)[start:end]
            break
    
    if not original_lines:
        return code
    
    # Replace the function
    new_lines = lines[:start_idx] + original_lines + lines[end_idx:]
    
    return ''.join(new_lines)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
