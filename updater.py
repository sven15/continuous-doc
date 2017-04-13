import configparser
import os
from subprocess import Popen, PIPE
import shutil
import logging
import sys
import tempfile
import json


def setup_custom_logger(name):
	formatter = logging.Formatter(fmt='%(asctime)s %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
	handler = logging.FileHandler('log.txt', mode='w')
	handler.setFormatter(formatter)
	screen_handler = logging.StreamHandler(stream=sys.stdout)
	screen_handler.setFormatter(formatter)
	logger = logging.getLogger(name)
	logger.setLevel(logging.DEBUG)
	logger.addHandler(handler)
	logger.addHandler(screen_handler)
	return logger


def readFile(filePath):
	if(os.path.isfile(filePath)):
		f = open(filePath, 'r')
		content = f.read()
		f.close()
		return content
	else:
		return False


def writeFile(path,content):
	f = open(path,'w')
	f.write(content)
	f.close()


def readConfig(filename):
	config = configparser.ConfigParser()
	config.sections()
	config.read(filename)
	return config


def readJSON(filename):
	content = readFile(filename)
	if content:
		content = json.loads(content)
		return content
	return False


def writeConfig(config, filename):
	with open(filename, 'w') as configfile:
		config.write(configfile)


def daps(repoName, dcFile, buildType):
	my_env = os.environ.copy()
	procDaps = Popen(["cd "+repoName+" && daps clean"], env=my_env, shell=True, stdout=PIPE, stderr=PIPE)
	procDaps.wait()
	procDaps = Popen(["cd "+repoName+" && daps -d "+dcFile+" "+buildType], env=my_env, shell=True, stdout=PIPE, stderr=PIPE)
	procDaps.wait()
	error = procDaps.stderr.read().decode("utf-8")
	if error != "":
		logger.warning("... ... Error: "+error)
	resultPath = procDaps.stdout.read().decode("utf-8").strip('\n')
	logger.info("... ... Result: "+resultPath)
	if os.path.isdir(resultPath) or os.path.isfile(resultPath):
		return resultPath
	else:
		return False


def moveResult(src, dst):
	if not os.path.isdir(dst):
		os.makedirs(dst)
	logger.debug("... ... mv "+src+" "+dst)
	procMv = Popen(["mv "+src+" "+dst], shell=True, stdout=PIPE, stderr=PIPE)
	procMv.wait()


def buildPdf(confMain, repoName, dcFile, docPath):
	buildDir = dcFile[3:]
	resultPath = daps(repoName, dcFile, 'pdf')
	if isinstance(resultPath, str):
		moveResult(resultPath, docPath+'/pdf')
		return True
	return False


def buildHtml(confMain, repoName, dcFile, docPath):
	buildDir = dcFile[3:]
	resultPath = daps(repoName, dcFile, 'html')
	if isinstance(resultPath, str):
		moveResult(resultPath+"*", docPath+'/html')


def buildSingleHtml(confMain, repoName, dcFile, docPath):
	buildDir = dcFile[3:]
	resultPath = daps(repoName, dcFile, 'html --single')
	if isinstance(resultPath, str):
		moveResult(resultPath+"*", docPath+'/single-html')
		return True
	return False


def buildEpub(confMain, repoName, dcFile, docPath):
	buildDir = dcFile[3:]
	resultPath = daps(repoName, dcFile, 'epub')
	if isinstance(resultPath, str):
		moveResult(resultPath, docPath+'/epub')
		return True
	return False


def docInJson(confMain, confDocs, resultJson, documentation):
	try:
		null = resultJson[documentation]
	except KeyError:
		logger.info("Init JSON for {}".format(documentation))
		resultJson.update(initJson(confMain, confDocs,documentation))
	return resultJson


def getCommitHash(resultJson, documentation):
	try:
		lastBuildCommit = resultJson[documentation]['source']['commit']
	except KeyError:
		logger.info("No build for {}".format(documentation))
		lastBuildCommit = "null"
	return lastBuildCommit


def iterateTypes(confMain, confDocs, resultJson, documentation, repoName, dcFile):
	for buildType in confDocs[documentation]['formats'].split(','):
		docPath = confMain['www']['path']+confDocs[documentation]['language']+"/"+documentation+"/"+str(resultJson[documentation]['build'])
		buildType = buildType.strip()
		if buildType == 'html':
			logger.debug("... HTML")
			if buildHtml(confMain, repoName, dcFile, docPath):
				resultJson[documentation]['status']['html'] = "success"
			else:
				resultJson[documentation]['status']['html'] = "failed"
		if buildType == 'pdf':
			logger.debug("... PDF")
			if buildPdf(confMain, repoName, dcFile, docPath):
				resultJson[documentation]['status']['pdf'] = "success"
			else:
				resultJson[documentation]['status']['pdf'] = "failed"
		if buildType == 'single-html':
			logger.debug("... SINGLE-HTML")
			if buildSingleHtml(confMain, repoName, dcFile, docPath):
				resultJson[documentation]['status']['single-html'] = "success"
			else:
				resultJson[documentation]['status']['single-html'] = "failed"
		if buildType == 'epub':
			logger.debug("... EPUB")
			if buildEpub(confMain, repoName, dcFile, docPath):
				resultJson[documentation]['status']['epub'] = "success"
			else:
				resultJson[documentation]['status']['epub'] = "failed"
	return resultJson


def build(confMain, confDocs, resultJson):
	for documentation in confDocs:
		if documentation == "DEFAULT":
			continue
		resultJson = docInJson(confMain, confDocs, resultJson, documentation)
		lastBuildCommit = getCommitHash(resultJson, documentation)
		branch = confDocs[documentation]['branch']
		repoName = confDocs[documentation]['source'].split('/')[-1]
		gitUpdate(repoName, confDocs[documentation]['source'], branch)
		if gitLastCommit(repoName, branch) == lastBuildCommit:
			logger.info('Already up to date: '+documentation)
			continue
		logger.info('Building: '+documentation)
		dcFile = confDocs[documentation]['dc']
		resultJson[documentation]['build'] = resultJson[documentation]['build'] + 1
		resultJson = iterateTypes(confMain, confDocs, resultJson, documentation, repoName, dcFile)
		try:
			os.remove(confMain['www']['path']+confDocs[documentation]['language']+"/"+documentation+"/current")
		except FileNotFoundError:
			pass
		resultJson[documentation]['source']['commit'] = gitLastCommit(repoName, branch)
		os.symlink(docPath, confMain['www']['path']+confDocs[documentation]['language']+"/"+documentation+"/current")
		writeFile(confMain['www']['path']+"json/"+confMain['www']['build']+".json", json.dumps(resultJson))
	return resultJson


def gitUpdate(repoName, repoUrl, buildBranch):
	my_env = os.environ.copy()
	if not os.path.isdir(repoName):
		procClone = Popen(["/usr/bin/git clone "+repoUrl], env=my_env, shell=True, stdout=PIPE, stderr=PIPE)
		procClone.wait()
	procCheckout = Popen(["cd "+repoName+" && /usr/bin/git checkout "+buildBranch], env=my_env, shell=True, stdout=PIPE, stderr=PIPE)
	procCheckout.wait()
	procPull = Popen(["cd "+repoName+" && /usr/bin/git pull"], env=my_env, shell=True, stdout=PIPE, stderr=PIPE)
	procPull.wait()


def gitLastCommit(repoName, buildBranch):
	cmd = "/usr/bin/git --no-pager -C {} log -n 1 --pretty=format:\"%H\" {}".format(repoName, buildBranch)
	process = Popen([cmd], shell=True, stdout=PIPE, stderr=PIPE)
	process.wait()
	if "path not in the" in process.stderr.read().decode("utf-8"):
		raise GitInvalidBranchName(self.getRepoPath(), branch)
	return process.stdout.read().decode("utf-8")


def genIndex(confMain, confDocs):
	pass


def initJson(docMain, docConf, documentation):
	newJson = {
		documentation: {
			"build": 0,
			"build_date": "2017-04-12 12:45:00 UTC+00:00",
			"version": docConf[documentation]['version'],
			"product": docConf[documentation]['product'],
			"name": docConf[documentation]['name'],
			"language": docConf[documentation]['language'],
			"type": docConf[documentation]['type'],
			"format": {	},
			"source": {
				"url": docConf[documentation]['source'],
				"branch": docConf[documentation]['branch'],
				"commit": "null"
			},
			"status": {}
		}
	}
	return newJson


def main():
	confMainFile = 'main.conf'
	confMain = readConfig(confMainFile)
	confMain['www']['build'] = str(int(confMain['www']['build']) + 1)
	writeConfig(confMain, confMainFile)
	resultJson = readJSON(confMain['www']['path']+'current.json')
	if resultJson == False:
		os.makedirs(confMain['www']['path']+"json")
		resultJson = {}
	confDocsFile = 'docs.conf'
	confDocs = readConfig(confDocsFile)
	resultJson = build(confMain, confDocs, resultJson)
	try:
		os.remove(confMain['www']['path']+"current.json")
	except FileNotFoundError:
		pass
	os.symlink(confMain['www']['path']+"json/"+confMain['www']['build']+".json", confMain['www']['path']+"current.json")


logger = setup_custom_logger('ContinuousDoc')
if __name__ == "__main__":
	main()
