#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @arg: qiniu/docx/docx/cmd/godir github
import os
import json
import sys
import re
import errno

re_kv = re.compile(r"^(\w+):\s*([^$]*)")
re_cmt = re.compile(r"^(\s*\*/|/\*\*+|\s*\*|//\s*)")

def get_json(filepaths):
	alldata = []
	for filepath in filepaths:
		data = os.popen("go2json %s" % filepath).read()
		data = json.loads(data)
		alldata.extend(data["decls"])
	f = open(filepath, "r")
	package = [l[7:].strip() for l in f.read().split("\n") if l.startswith("package")][0]
	f.close()
	alldata.append(dict(package=package))
	return alldata

def decode_type(decl_type):
	ptr = False
	if "ptr" in decl_type:
		ptr = True
		decl_type = decl_type["type"]
	
	array = None
	if "array" in decl_type and "type" in decl_type:
		array = decl_type["array"]
		decl_type = decl_type["type"]

	for i in [i for i in decl_type]:
		for j in decl_type[i]:
			decl_type["%s_%s" % (i, j)] = decl_type[i][j]
	del decl_type[i]
	if ptr:
		decl_type["ptr"] = True
	if array:
		decl_type["array"] = array
	return decl_type

def deal_func_doc_line(scheme, content, decl, ds):
	if scheme == "beief":
		ds["beief"] = ''.join(content).strip()
		return

	if scheme in ["args", "returns"]:
		content = filter(None, content)
		for arg_string in content:
			args_desc = re_kv.findall(arg_string)[0]
			for arg in decl[scheme]:
				if arg["name"] == args_desc[0]:
					arg["doc"] = args_desc[1]
					break
		return

	ds[scheme] = content

def subcomment_prefix(doc_item):
	return re_cmt.sub("", doc_item).strip()

def make_names_match_regex(names):
	regex = "\:|^".join(names)
	if len(regex) > 0:
		regex = "^%s\:\s*|" % regex
	regex += "^\@"
	return re.compile(regex)

def deal_type_doc(decl):
	if "doc" not in decl:
		return
	docs = decl["doc"]
	fields = list()
	if "struct" in decl and "vars" in decl["struct"]:
		fields = [i["name"] for i in decl["struct"]["vars"]]
	r = make_names_match_regex(fields)

	decl["doc"] = deal_doc(deal_type_doc_line, docs, decl, r)

def deal_type_doc_line(scheme, content, decl, ds):
	if scheme == "beief":
		ds[scheme] = ''.join(content).strip()
		return

	if scheme == "vars":
		for doc in content:
			if doc == "":
				continue
			kv = re_kv.findall(doc)[0]
			try:
				for var in decl["struct"]["vars"]:
					if var["name"] == kv[0]:
						var["doc"] = kv[1]
						break
			except KeyError:
				pass
		return

def deal_func_doc(decl):
	if "doc" not in decl:
		return
	docs = decl["doc"]
	args = list()
	if "args" in decl:
		args = [i["name"] for i in decl["args"]]
	if "returns" in decl:
		args.extend([i["name"] for i in decl["returns"] if "name" in i])

	r = make_names_match_regex(args)

	decl["doc"] = deal_doc(deal_func_doc_line, docs, decl, r)

def deal_doc(deal_line_func, docs, decl, r):
	ds = dict(
		beief = ""
	)
	current_scheme = "beief"
	current_content = [""]
	for doc in docs:
		doc = doc.split("\n")
		doc = [subcomment_prefix(s) for s in doc]

		for d in doc:
			d = d.strip()
			if d.startswith("@"):
				deal_line_func(current_scheme, current_content, decl, ds)
				current_scheme = re.findall(r"@(\w+)", d)[0]
				current_content = [d[len(current_scheme)+1:].strip()]
				continue

			if not r.match(d):
				d = " %s" % d if not d == "" else "\n"
				if current_content[len(current_content)-1].endswith("\n"):
					d = d[1:]
				current_content[len(current_content)-1] += d
			else:
				current_content.append(d)

	deal_line_func(current_scheme, current_content, decl, ds)
	return ds

def format_go2json(filepath, json_output=False):
	result = {}
	comment = []
	decls = get_json(filepath)
	for decl_dict in decls:
		key = decl_dict.keys()[0]
		decl = decl_dict[key]

		if key == 'comment':
			comment.append(decl.strip())
			continue

		if key == 'nl':
			comment = []
			continue
			
		if key == "package":
			result["pkg"] = decl
			continue

		if key not in ['typedef', 'import', 'func']:
			print 'not support for %s' % key
			continue

		if len(comment) > 0:
			decl['doc'] = comment
			comment = []

		if key not in result:
			result[key] = dict()
		sub_key = None

		if key == "import":
			pkg = decl["pkg"][1: -1]
			sub_key = pkg

			if "name" in decl:
				sub_key = decl["name"]
			elif pkg.find("/") >= 0:
				sub_key = pkg[pkg.find("/")+1: ]
			decl = pkg

		elif key == "typedef":
			sub_key = decl["name"]
			if "struct" in decl and "vars" in decl["struct"]:
				for var in decl["struct"]["vars"]:
					var["type"] = decode_type(var["type"])

			deal_type_doc(decl)

		elif key == "func":
			sub_key = decl["name"]
			if "returns" in decl:
				for returns in decl["returns"]:
					returns["type"] = decode_type(returns["type"])

			if "args" in decl:
				for i, args in enumerate(decl["args"]):
					if "type" in args:
						args["type"] = decode_type(args["type"])
						ptr = i - 1
						while "type" not in decl["args"][ptr]:
							decl["args"][ptr]["type"] = args["type"]
							ptr -= 1

			deal_func_doc(decl)

			if "recvr" in decl:
				# struct method
				struct_name = decl["recvr"]["type"]["name"]
				if "typedef" not in result:
					result["typedef"] = dict()
				if struct_name not in result["typedef"]:
					result["typedef"][struct_name] = dict()
				struct_dict = result["typedef"][struct_name]
				if not "struct" in struct_dict:
					struct_dict["struct"] = dict()
				struct = struct_dict["struct"]
				if not "func" in struct:
					struct["func"] = dict()
				struct["func"][decl["name"]] = decl
				if "name" not in struct_dict:
					struct_dict["name"] = struct_name
				continue

		result[key][sub_key] = decl
	if not json_output:
		return result
	return json.dumps(result)

def walk_pathes(filepath, filter_regex):
	pathes = []
	for path in os.walk(filepath):
		if path[0].find('/.') > 0:
			continue
		if len(path[2]) == 0:
			continue
		
		filenames = []
		_path = path[0].replace(filepath + '/', "")
		for filename in path[2]:
			if not filename.endswith(".go") or filename.endswith("_test.go"):
				continue
			if filter_regex and not len(re.findall(filter_regex, path[0])) > 0:
				continue
			filenames.append(_path + "/" + filename)
		if len(filenames) <= 0:
			continue
		pathes.append((_path, filenames))
	return pathes

def ensure_filepath(filepath):
	if filepath.endswith(".go"):
		return filepath
	
	if filepath.endswith("/"):
		filepath = filepath[: -1]

	if not os.path.exists(filepath):
		sys.exit(errno.ENOENT)
	
	if os.path.exists("%s/src" % filepath):
		filepath = "%s/src" % filepath
	return filepath

def do(filepath, filter_regex, json_output=False):
	filepath = ensure_filepath(filepath)
	if filepath.endswith(".go"):
		return format_go2json(filepath, json_output)

	pathes = walk_pathes(filepath, filter_regex)
	
	if len(pathes) <= 0:
		print "files not found"
		sys.exit(errno.ENOENT)

	datas = []
	for folder, path in pathes:
		path = ["%s/%s" % (filepath, p) for p in path]
		data = format_go2json(path)
		data["pkg_path"] = folder
		datas.append(data)
	return datas

if __name__ == "__main__":
	if len(sys.argv) <= 1:
		exit("miss file")

	filter_regex = sys.argv[2] if len(sys.argv) >= 3 else None
	do(sys.argv[1], filter_regex)