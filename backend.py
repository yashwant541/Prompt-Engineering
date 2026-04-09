from flask import Flask, request, render_template, jsonify
from flask_cors import CORS
import ast
import inspect
import tempfile
import os
from pathlib import Path

app = Flask(__name__)
CORS(app)

class CodeAnalyzer:
    def __init__(self, code_string=None, file_path=None):
        self.code_string = code_string
        self.file_path = file_path
        self.tree = None
        self.functions = []
        
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
        
        return structure
    
    def _extract_classes(self):
        """Extract classes from the code"""
        classes = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                first_line = node.lineno
                last_line = node.end_lineno if hasattr(node, 'end_lineno') else node.body[-1].lineno
                line_count = last_line - first_line + 1
                
                classes.append({
                    'name': node.name,
                    'start_line': node.lineno,
                    'end_line': node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
                    'line_count': line_count,
                    'methods': [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
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
            'imports_removed': []
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)
