import boto3
import datetime
import json
import pytz
import time

# Setting up all required API clients
ecs = boto3.client('ecs')
dynamodb = boto3.resource('dynamodb')
asg = boto3.client('autoscaling')
ec2 = boto3.client('ec2')

# function for time interval test
def is_between(time, time_range):
  if time_range[1] < time_range[0]:
    return time >= time_range[0] or time <= time_range[1]
  return time_range[0] <= time <= time_range[1]

# function for scheduler dynamodb table and signaling to start/stop
def action_based_on_schedule():
  table = dynamodb.Table('DYNAMO_DB_TABLE')
  response = table.get_item(
      Key={
          'name': 'office-hours',
          'type': 'period'
      }
  )
  item = response['Item']
  utc_now = pytz.utc.localize(datetime.datetime.utcnow())
  time = utc_now.astimezone(pytz.timezone("Europe/Bucharest"))
  week_day = time.strftime('%a')
  time = time.strftime('%H:%M')
  begin_time = item['begintime']
  begin_time = datetime.datetime.strptime(begin_time, '%H:%M')
  begin_time = begin_time.strftime('%H:%M')
  end_time = item['endtime']
  end_time = datetime.datetime.strptime(end_time, '%H:%M')
  end_time = end_time.strftime('%H:%M')
  if is_between(time, (begin_time, end_time)) == True:
    action = 'stop'
  else:
    action = 'start'
  if week_day == 'Sun':
    action = 'stop'
  return action


# services processing
def stop_service_tasks(clusterName):
  table = dynamodb.Table('scheduler-ecs')
  paginator = ecs.get_paginator('list_services')
  response_iterator = paginator.paginate(cluster=clusterName)
  for i in response_iterator:
    serviceArns = i['serviceArns']
    for serviceArn in serviceArns:
      serviceName = serviceArn.split("/")[1]
      paginator = ecs.get_paginator('list_tasks')
      response_iterator = paginator.paginate(cluster=clusterName, serviceName=serviceName,desiredStatus='RUNNING')
      for i in response_iterator:
        runningTasksCount = len(i['taskArns'])
        if runningTasksCount > 0:
          response = table.put_item(
            Item={
                'serviceArn': serviceArn,
                'ClusterName': clusterName,
                'runningTasksCount': runningTasksCount
            }
          )
      ecs.update_service(cluster=clusterName, service=serviceArn, desiredCount=0)
  return runningTasksCount

def start_service_tasks(clusterName):
  table = dynamodb.Table('scheduler-ecs')
  paginator = ecs.get_paginator('list_services')
  response_iterator = paginator.paginate(cluster=clusterName)
  for i in response_iterator:
    serviceArns = i['serviceArns']
    for serviceArn in serviceArns:
      response = table.get_item(
        Key={
            'serviceArn': serviceArn
            }
      )
      del response['ResponseMetadata']
      if bool(response):
          item = response['Item']
          desiredTasksCount = int(item['runningTasksCount'])
          ecs.update_service(cluster=clusterName, service=serviceArn, desiredCount=desiredTasksCount)

# ecs nodes processing - ASG
def stop_ecs_nodes(asgNames):
  table = dynamodb.Table('scheduler-asg')
  for asgName in asgNames:
    asg_response = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asgName])
    for i in asg_response['AutoScalingGroups']:
      minnSize = i['MinSize']
      desireddCapacity = i['DesiredCapacity']
      if desireddCapacity > 0:
        response = table.put_item(
          Item={
              'asgName': asgName,
              'MinSize': minnSize,
              'DesiredCapacity': desireddCapacity
          }
        )
    asg.update_auto_scaling_group(
      AutoScalingGroupName=asgName,
      MinSize=0,
      DesiredCapacity=0
    )

def start_ecs_nodes(asgNames):
  table = dynamodb.Table('scheduler-asg')
  for asgName in asgNames:
    asg_response = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asgName])
    response = table.get_item(
      Key={
           'asgName': asgName
          }
    )
    item = response['Item']
    minnSize = int(item['MinSize'])
    desireddCapacity = int(item['DesiredCapacity'])
    asg.update_auto_scaling_group(
      AutoScalingGroupName=asgName,
      MinSize=minnSize,
      DesiredCapacity=desireddCapacity
    )

# get tagged cluster list
def get_ecs_clusters():
  paginator = ecs.get_paginator('list_clusters')
  response_iterator = paginator.paginate()
  clusterNames = []
  for i in response_iterator:
    clusterArns = i['clusterArns']
    for clusterArn in clusterArns:
      clusterName = clusterArn.split("/")[1]
      clusterNames.append(clusterName)
  response = ecs.describe_clusters(clusters=clusterNames,include=['TAGS'])
  scheduledEcsClusters = []
  for j in response['clusters']:
    if (len(j['tags']) > 0):
      tagsList = j['tags']
      for g in tagsList:
        responseKey = g['key']
        responseValue = g['value']
        if (responseKey == 'ecs-scheduler') and (responseValue == 'yes'):
          resultedEcsCluster = j['clusterName']
          scheduledEcsClusters.append(resultedEcsCluster)
  return scheduledEcsClusters

# get asg list coresponding to clusters
def get_asg_groups(clusterNames):
  response = asg.describe_auto_scaling_groups()
  selected_asg = []
  all_asg = response['AutoScalingGroups']
  for i in range(len(all_asg)):
      all_tags = all_asg[i]['Tags']
      for j in range(len(all_tags)):
          if all_tags[j]['Key'] == 'Name':
                  asg_name = all_tags[j]['Value']
          for clusterName in clusterNames:
            asgName = all_tags[j]['Value']
            asgName = asgName.split(" ")[0]
            if clusterName == asgName:
                  selected_asg.append(all_asg[i]['AutoScalingGroupName'])
  return selected_asg

# main handler function
def lambda_handler(event, context):
  clusters = get_ecs_clusters()
  print("Tagged ECS cluster list: ", clusters)
  asgs = get_asg_groups(clusters)
  print("Corresponding ECS clusters ASGs: ", asgs)
  schedule_action = action_based_on_schedule()
  if schedule_action == 'stop':
    print('Tagged clusters and their coresponding ASGs will be STOPED as scheduled.')
    for clusterItem in clusters:
      runningTasks = stop_service_tasks(clusterItem)
      # while runningTasks != 0:
      stop_service_tasks(clusterItem)
      time.sleep(60)
      stop_ecs_nodes(asgs)
  else:
   print('Tagged clusters and their coresponding ASGs will be STARTED as scheduled.')
   start_ecs_nodes(asgs)
   time.sleep(150)
   for clusterItem in clusters:
     start_service_tasks(clusterItem)
