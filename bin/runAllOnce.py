#!/usr/bin/python
import json
import os
import sys
import time
from datetime import datetime

import common


# usage
def usage():
    print "usage: " \
          + common.sarg(0) \
          + " group_count process_per_group destination_count client_per_destination duration warmup enable_debug enablee_profiling"
    sys.exit(1)


if len(sys.argv) not in [7, 9]:
    usage()

NUM_GROUPS = common.iarg(1)
NUM_PROCESSES = common.iarg(2)
DESTINATION_COUNT = common.iarg(3)
CLIENT_PER_DESTINATION = common.iarg(4)

DURATION = common.iarg(5)
WARMUP = common.iarg(6)
PAYLOAD_SIZE = 96  # 196

# ******
# whitecast method: send to separate groups of server, then agreegate all results
# OR 1 client only send to group of servers
WHITE_CAST = True
WHITE_CAST = False
# ******

if len(sys.argv) == 9:
    DEBUG = common.barg(7)
    PROFILING = common.barg(8)
else:
    DEBUG = False
    PROFILING = False

if WHITE_CAST:
    NUM_CLIENTS = (NUM_GROUPS / DESTINATION_COUNT) * CLIENT_PER_DESTINATION
else:
    NUM_CLIENTS = CLIENT_PER_DESTINATION

print "Use " + str(NUM_CLIENTS) + " clients"

DELAY = False
# RDMA config
CONF_QUEUE_LENGTH = 8
CONF_NUM_PROCESSES = NUM_PROCESSES
CONF_SERVICE_TIMEOUT = 1
CONF_POLLING = True
CONF_MAX_INLINE = 64
CONF_PORT = 9000
CONF_SIGNAL_INTERVAL = 4

ROLE_CLIENT = 1
ROLE_SERVER = 2
ROLE_BOTH = 3

RDMA_NODES = common.RDMA_NODES

CLASS_BENCH = "ch.usi.dslab.lel.ramcast.benchmark.BenchAgent"

debug_log_dir = '{}/bin'.format(common.PATH_LIBRAMCAST_HOME)
log_dir = '{}/logs/{}c-{}g-{}d-{}p-{}'.format(common.PATH_LIBRAMCAST_HOME, NUM_CLIENTS, NUM_GROUPS, DESTINATION_COUNT,
                                              NUM_PROCESSES, datetime.now().strftime('%Y-%m-%d-%H-%M-%S'))
java_cmd = "java -XX:+UseConcMarkSweepGC -XX:SurvivorRatio=15 -XX:+UseParNewGC -Xms3g -Xmx3g"

if PROFILING:
    java_cmd = java_cmd + " -agentpath:" + common.PATH_PROFILING
if DEBUG:
    log4j_conf = common.PATH_LIBRAMCAST_HOME + '/bin/logback-debug.xml'
    java_cmd = java_cmd + " -agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=5005"
else:
    log4j_conf = common.PATH_LIBRAMCAST_HOME + '/bin/logback.xml'

java_cmd = java_cmd + " -Dlogback.configurationFile=" + log4j_conf

java_cmd = java_cmd + common.JAVA_CLASSPATH

config_file = '{}/bin/systemConfigs/generatedSystemConfig{}g{}p.json'.format(common.PATH_LIBRAMCAST_HOME, NUM_GROUPS,
                                                                             NUM_PROCESSES)

num_servers = NUM_PROCESSES * NUM_GROUPS
node_used = max(num_servers, NUM_CLIENTS)


def gen_config():
    config = dict()
    config["queueLength"] = CONF_QUEUE_LENGTH
    config["zkHost"] = common.ZK_HOST
    config["nodePerGroup"] = CONF_NUM_PROCESSES
    config["servicetimeout"] = CONF_SERVICE_TIMEOUT
    config["polling"] = CONF_POLLING
    config["maxinline"] = CONF_MAX_INLINE
    config["signalInterval"] = CONF_SIGNAL_INTERVAL
    config["debug"] = DEBUG
    config["delay"] = DELAY

    config["group_members"] = []
    i = 0
    p = 0
    g = 0
    while i < node_used:
        # if i < NUM_CLIENTS and i < num_servers:
        #     role = ROLE_BOTH
        # elif i < NUM_CLIENTS:
        #     role = ROLE_CLIENT
        # elif i < num_servers:
        #     role = ROLE_SERVER

        config["group_members"].append({
            "gid": g,  # if role == ROLE_BOTH or role == ROLE_SERVER else -1,
            "nid": p,  # if role == ROLE_BOTH or role == ROLE_SERVER else -1,
            "port": CONF_PORT,
            "host": RDMA_NODES[i],
            # "role": role
        })
        i += 1
        p += 1
        if p == NUM_PROCESSES:
            p = 0
            g += 1
    systemConfigurationFile = open(config_file, 'w')
    json.dump(config, systemConfigurationFile, sort_keys=False, indent=4, ensure_ascii=False)
    systemConfigurationFile.flush()
    systemConfigurationFile.close()


def run():
    i = 0
    p = 0
    g = 0
    cmds = []
    while i < node_used:
        cmd = [java_cmd, '-DLOG_DIR=' + debug_log_dir, '-DGROUPID=' + str(g), '-DNODEID=' + str(p), CLASS_BENCH,
               "-c", config_file, "-s", PAYLOAD_SIZE,
               "-gid", g, "-nid", p, "-cid", i,
               "-d", DURATION, "-gh", common.GATHERER_HOST, "-gp", common.GATHERER_PORT, "-gd", log_dir, "-gw",
               WARMUP * 1000]
        cmdString = ' '.join([str(val) for val in cmd])
        cmds.append([RDMA_NODES[i], cmdString])
        i += 1
        p += 1
        if p == NUM_PROCESSES:
            p = 0
            g += 1

    dest_from = 0
    i = 0
    skip = 0

    if WHITE_CAST:
        while i < len(cmds) or i < NUM_CLIENTS:
            if dest_from < NUM_GROUPS:
                for c in range(0, CLIENT_PER_DESTINATION):
                    cmds[i][1] = cmds[i][1] + ' ' + ' '.join(
                        ["-df", str(dest_from), "-dc", str(DESTINATION_COUNT), "-isClient", "1"])
                    i = i + 1
                    if i == len(cmds) or i - skip == NUM_CLIENTS:
                        break
                # hack to make sure client is a process in the destination group
                if CLIENT_PER_DESTINATION < NUM_PROCESSES:
                    skip = skip + (NUM_PROCESSES - CLIENT_PER_DESTINATION)
                    i = i + (NUM_PROCESSES - CLIENT_PER_DESTINATION)
                dest_from = dest_from + DESTINATION_COUNT
            else:
                break
    else:
        # while i < len(cmds) and i < NUM_CLIENTS:
        #     if dest_from < NUM_GROUPS:
        #         for c in range(0, CLIENT_PER_DESTINATION):
        #             cmds[i][1] = cmds[i][1] + ' ' + ' '.join(
        #                 ["-df", str(dest_from), "-dc", str(DESTINATION_COUNT), "-isClient", "1"])
        #             i = i + 1
        #             if i == len(cmds) or i - skip == NUM_CLIENTS:
        #                 break
        #         # hack to make sure client is a process in the destination group
        #         if CLIENT_PER_DESTINATION < NUM_PROCESSES:
        #             skip = skip + (NUM_PROCESSES - CLIENT_PER_DESTINATION)
        #             i = i + (NUM_PROCESSES - CLIENT_PER_DESTINATION)
        #         dest_from = dest_from + DESTINATION_COUNT
        #     else:
        #         break

        # seperating client and servers
        i = 3
        while i < len(cmds) and i < NUM_CLIENTS + 3:
            if dest_from < NUM_GROUPS:
                for c in range(0, CLIENT_PER_DESTINATION):
                    cmds[i][1] = cmds[i][1] + ' ' + ' '.join(
                        ["-df", str(dest_from), "-dc", str(DESTINATION_COUNT), "-isClient", "1"])
                    i = i + 1
                    if i == len(cmds) or i - skip == NUM_CLIENTS + 3:
                        break
                # hack to make sure client is a process in the destination group
                if CLIENT_PER_DESTINATION < NUM_PROCESSES:
                    skip = skip + (NUM_PROCESSES - CLIENT_PER_DESTINATION)
                    i = i + (NUM_PROCESSES - CLIENT_PER_DESTINATION)
                dest_from = dest_from + DESTINATION_COUNT
            else:
                break

    for cmd in cmds:
        print cmd[0], cmd[1]
        common.sshcmdbg(cmd[0], cmd[1])

    # start gatherer
    cmd = [java_cmd, common.CLASS_GATHERER, WARMUP * 1000, common.GATHERER_PORT, log_dir,
           "throughput", "client_overall", NUM_CLIENTS,
           "latency", "client_overall", NUM_CLIENTS,
           "latencydistribution", "client_overall", NUM_CLIENTS,
           ]

    # seperating client and servers
    cmd = [java_cmd, common.CLASS_GATHERER, WARMUP * 1000, common.GATHERER_PORT, log_dir,
           "throughput", "client_overall", NUM_CLIENTS,
           ]

    cmdString = ' '.join([str(val) for val in cmd])
    common.localcmd(cmdString)


gen_config()
time.sleep(1)

if common.ENV_EMULAB:
    # need to sync this sysConfig with other instances
    os.system(
        "/users/lel/apps/libramcast/libRamcastV3/bin/emulab/sync-code.sh /users/lel/apps/libramcast/libRamcastV3/bin/systemConfigs " + str(
            node_used + len(common.EMULAB_DEAD_NODES)))
    time.sleep(3)

run()

common.localcmd(common.APP_CLEANER)
time.sleep(1)
print "===================================\n             Throughput                 \n==================================="
common.localcmd("cat " + log_dir + "/throughput_client_overall_aggregate.log")
print "===================================\n             Latency                    \n==================================="
common.localcmd("cat " + log_dir + "/latency_client_overall_average.log")
print "==================================="
