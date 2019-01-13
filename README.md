# ECS scheduler

* built on 30 Dec 2018 to schedule the graceful stop of ECS cluster nodes and its service tasks
* during ASG and services tasks stop, their properties are
  saved in 2 dynamodb tables (min/desired count for asg and running tasks count for ECS services)
* this scheduler integrates with an existing aws-instance-scheduler (see link bellow)
* Sunday is hardcoded in this initial version and during Sunday all ECS clusters are stopped
* during start the ASG and ECS services states are restored as per dynamodb entries
* inspired by https://github.com/aws-samples/ecs-cid-sample and https://github.com/awslabs/aws-instance-scheduler

# requirements

* dynamoDB tables scheduler-asg with key asgName and scheduler-ecs with key serviceArn must be pre-created
* dynamoDB tables from the aws-instance-scheduler must be pre-create
* python 3.7
* mechanism for calling the lambda function
* tagging target ecs clusters with ecs-scheduler:yes

# deployment using sam
1.
sam build --use-container
2.
sam package \
    --output-template-file packaged.yaml \
    --s3-bucket ecs-scheduler
3.
sam deploy \
    --template-file packaged.yaml \
    --stack-name ecs-scheduler \
    --capabilities CAPABILITY_IAM \
    --region eu-central-1


v1.0.2
Cosmin Banciu
