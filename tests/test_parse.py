import pytest
from pydantic import ValidationError

from pipeline_runner.config import config
from pipeline_runner.models import (
    AwsCredentials,
    Definitions,
    Image,
    ParallelStep,
    Pipe,
    Pipeline,
    PipelineSpec,
    Service,
    Step,
    StepSize,
    StepWrapper,
    Trigger,
    Variable,
    Variables,
)


def test_parse_empty_definitions():
    defs = Definitions.parse_obj({})

    assert defs.caches == {}
    assert defs.services == {}


def test_parse_caches():
    caches = {
        "poetry": "~/.cache/pypoetry",
        "pip": "${HOME}/.cache/pip",
    }

    value = {"caches": caches}

    defs = Definitions.parse_obj(value)

    assert defs.caches == caches


def test_parse_services():
    services = {
        "docker": {"memory": 3072},
        "postgres": {
            "image": "postgres:13",
            "variables": {
                "POSTGRES_DB": "pg-db",
                "POSTGRES_USER": "pg-user",
                "POSTGRES_PASSWORD": "pg-passwd",
            },
        },
        "mysql": {
            "image": "mysql",
            "environment": {
                "MYSQL_DB": "my-db",
                "MYSQL_USER": "my-user",
                "MYSQL_PASSWORD": "my-passwd",
            },
        },
    }

    value = {"services": services}

    defs = Definitions.parse_obj(value)

    services = {
        "docker": Service(image=None, variables={}, memory=3072),
        "postgres": Service(
            image="postgres:13",
            variables={
                "POSTGRES_DB": "pg-db",
                "POSTGRES_USER": "pg-user",
                "POSTGRES_PASSWORD": "pg-passwd",
            },
            memory=config.service_container_default_memory_limit,
        ),
        "mysql": Service(
            image="mysql",
            environment={
                "MYSQL_DB": "my-db",
                "MYSQL_USER": "my-user",
                "MYSQL_PASSWORD": "my-passwd",
            },
            memory=config.service_container_default_memory_limit,
        ),
    }

    assert defs.services == services


def test_parse_image():
    name = "alpine:latest"
    user = 1000

    value = {"name": name, "run-as-user": user}

    image = Image.parse_obj(value)

    assert image == Image(name=name, run_as_user=user)


def test_parse_image_with_credentials():
    name = "private-repo/image"
    username = "my-username"
    password = "my-password"
    email = "my-email"

    value = {"name": name, "username": username, "password": password, "email": email}

    assert Image.parse_obj(value) == Image(name=name, username=username, password=password, email=email)


def test_parse_image_with_aws_credentials():
    name = "aws-repo/image"
    access_key_id = "access-key-id"
    secret_access_key = "secret-access-key"

    value = {"name": name, "aws": {"access-key": access_key_id, "secret-key": secret_access_key}}
    image = Image.parse_obj(value)

    assert image == Image(
        name=name, aws=AwsCredentials(access_key_id=access_key_id, secret_access_key=secret_access_key)
    )


def test_parse_image_with_aws_oidc_role():
    name = "alpine:latest"
    oidc_role = "some-role"

    value = {"name": name, "aws": {"oidc-role": oidc_role}}

    with pytest.raises(ValidationError) as exc_info:
        Image.parse_obj(value)

    assert "aws oidc-role not supported" in str(exc_info.value)


def test_parse_image_with_envvars():
    name = "alpine:latest"
    username = "my-username"
    password = "my-password"
    email = "my-email"
    access_key_id = "access-key-id"
    secret_access_key = "secret-access-key"

    value = {
        "name": "${IMAGE_NAME}",
        "username": "$REPO_USERNAME",
        "password": "$REPO_PASSWORD",
        "email": "$REPO_EMAIL",
        "aws": {"access-key": "$AWS_ACCESS_KEY_ID", "secret-key": "$AWS_SECRET_ACCESS_KEY"},
    }

    env_vars = {
        "IMAGE_NAME": name,
        "REPO_USERNAME": username,
        "REPO_PASSWORD": password,
        "REPO_EMAIL": email,
        "AWS_ACCESS_KEY_ID": access_key_id,
        "AWS_SECRET_ACCESS_KEY": secret_access_key,
    }

    image = Image.parse_obj(value)
    image.expand_env_vars(env_vars)

    expected = Image(
        name="${IMAGE_NAME}",  # Env vars in the name field are not expanded
        username=username,
        password=password,
        email=email,
        aws={"access-key": access_key_id, "secret-key": secret_access_key},
    )

    assert image == expected


def test_parse_pipeline_with_steps():
    spec = [
        {"step": {"name": "Step 1", "script": ["cat /etc/os-release", "exit 0"]}},
        {"step": {"name": "Step 2", "script": ["echo 'Step 2'"]}},
    ]

    pipeline = Pipeline.parse_obj(spec)

    step1 = StepWrapper(step=Step(name="Step 1", script=["cat /etc/os-release", "exit 0"]))
    step2 = StepWrapper(step=Step(name="Step 2", script=["echo 'Step 2'"]))
    expected = Pipeline(
        __root__=[
            step1,
            step2,
        ]
    )

    assert pipeline == expected


def test_parse_pipeline_with_parallel_steps():
    spec = [
        {"step": {"name": "Step 1", "script": ["cat /etc/os-release", "exit 0"]}},
        {
            "parallel": [
                {"step": {"name": "Parallel Step 1", "script": ["echo 'Parallel 1'"]}},
                {"step": {"name": "Parallel Step 2", "script": ["echo 'Parallel 2'"]}},
            ]
        },
    ]

    pipeline = Pipeline.parse_obj(spec)

    step1 = StepWrapper(step=Step(name="Step 1", script=["cat /etc/os-release", "exit 0"]))
    pstep1 = StepWrapper(step=Step(name="Parallel Step 1", script=["echo 'Parallel 1'"]))
    pstep2 = StepWrapper(step=Step(name="Parallel Step 2", script=["echo 'Parallel 2'"]))
    expected = Pipeline(
        __root__=[
            step1,
            ParallelStep(parallel=[pstep1, pstep2]),
        ]
    )

    assert pipeline == expected


def test_parse_pipeline_with_variables():
    spec = [
        {"variables": [{"name": "foo"}, {"name": "bar"}]},
        {"step": {"name": "Step 1", "script": ["cat /etc/os-release", "exit 0"]}},
    ]

    pipeline = Pipeline.parse_obj(spec)

    variables = Variables(variables=[Variable(name="foo"), Variable(name="bar")])
    step = StepWrapper(step=Step(name="Step 1", script=["cat /etc/os-release", "exit 0"]))
    expected = Pipeline(
        __root__=[
            variables,
            step,
        ]
    )

    assert pipeline == expected


def test_variables_can_only_be_the_first_element_of_the_pipelines():
    spec = [
        {"step": {"name": "Step 1", "script": ["cat /etc/os-release", "exit 0"]}},
        {"variables": [{"name": "foo"}, {"name": "bar"}]},
    ]

    with pytest.raises(ValidationError) as exc_info:
        Pipeline.parse_obj(spec)

    assert exc_info.value.model == Pipeline
    assert exc_info.value.errors() == [
        {"loc": ("__root__",), "msg": "'variables' can only be the first element of the list", "type": "value_error"}
    ]


def test_parse_step_with_default_values():
    spec = {"name": "Step 1", "script": ["cat /etc/os-release", "exit 0"]}

    step = Step.parse_obj(spec)

    assert step == Step(name="Step 1", script=["cat /etc/os-release", "exit 0"])


def test_parse_step_with_manual_trigger():
    spec = {"script": [], "trigger": "manual"}

    step = Step.parse_obj(spec)

    assert step.trigger == Trigger.Manual


def test_parse_step_with_double_size():
    spec = {"script": [], "size": "2x"}

    step = Step.parse_obj(spec)

    assert step.size == StepSize.Double


def test_parse_step_with_pipes():
    spec = {
        "script": [
            "echo a",
            {
                "pipe": "atlassian/trigger-pipeline:4.2.1",
                "variables": {
                    "BITBUCKET_USERNAME": "${TRIGGER_PIPELINE_USERNAME}",
                    "BITBUCKET_APP_PASSWORD": "${TRIGGER_PIPELINE_APP_PASSWORD}",
                    "REPOSITORY": "other-repo",
                    "CUSTOM_PIPELINE_NAME": "deploy",
                    "PIPELINE_VARIABLES": (
                        '[{"key": "PIPELINE_VAR_1", "value": "VALUE_1"}, '
                        '{ "key": "PIPELINE_VAR_2", "value": "VALUE_2"}, '
                        '{ "key": "PIPELINE_VAR_3", "value": "VALUE_3"}]'
                    ),
                    "WAIT": "true",
                },
            },
            "echo b",
        ],
        "after-script": [
            "echo c",
            {
                "pipe": "atlassian/trigger-pipeline:4.2.1",
                "variables": {
                    "BITBUCKET_USERNAME": "${TRIGGER_PIPELINE_USERNAME}",
                    "BITBUCKET_APP_PASSWORD": "${TRIGGER_PIPELINE_APP_PASSWORD}",
                },
            },
            "echo d",
        ],
    }

    parsed = Step.parse_obj(spec)

    pipe_a = Pipe(
        pipe="atlassian/trigger-pipeline:4.2.1",
        variables=spec["script"][1]["variables"],
    )

    pipe_b = Pipe(
        pipe="atlassian/trigger-pipeline:4.2.1",
        variables=spec["after-script"][1]["variables"],
    )

    assert parsed.script == [
        "echo a",
        pipe_a,
        "echo b",
    ]
    assert parsed.after_script == [
        "echo c",
        pipe_b,
        "echo d",
    ]


def test_parse_pipeline_with_env_vars():
    step_image = "step-image"
    service_image = "service-image"
    parallel_step_image = "parallel-image"

    spec = {
        "definitions": {"services": {"from_env": {"image": service_image, "variables": {"PASSWORD": "$PASSWORD"}}}},
        "pipelines": {
            "default": [
                {
                    "step": {
                        "name": "Test image from env",
                        "image": step_image,
                        "services": ["from_env"],
                        "script": ["cat /etc/os-release"],
                    },
                },
                {
                    "parallel": [
                        {
                            "step": {
                                "name": "Parallel 1",
                                "image": parallel_step_image,
                                "services": ["from_env"],
                                "script": ["cat /etc/os-release"],
                            }
                        },
                        {
                            "step": {
                                "name": "Parallel 2",
                                "image": parallel_step_image,
                                "services": ["from_env"],
                                "script": ["cat /etc/os-release"],
                            }
                        },
                    ],
                },
            ]
        },
    }

    password = "some-password"
    variables = {
        "PASSWORD": password,
    }

    parsed = PipelineSpec.parse_obj(spec)
    parsed.expand_env_vars(variables)

    expected = {
        "image": None,
        "definitions": {
            "caches": {},
            "services": {
                "from_env": {
                    "image": {
                        "name": service_image,
                        "username": None,
                        "password": None,
                        "email": None,
                        "run-as-user": None,
                        "aws": None,
                    },
                    "environment": {"PASSWORD": password},
                    "memory": 1024,
                }
            },
        },
        "clone": {"depth": None, "lfs": None, "enabled": None},
        "pipelines": {
            "default": [
                {
                    "step": {
                        "name": "Test image from env",
                        "script": ["cat /etc/os-release"],
                        "image": {
                            "name": step_image,
                            "username": None,
                            "password": None,
                            "email": None,
                            "run-as-user": None,
                            "aws": None,
                        },
                        "caches": [],
                        "services": ["from_env"],
                        "artifacts": [],
                        "after-script": [],
                        "size": StepSize.Simple,
                        "clone": {"depth": None, "lfs": None, "enabled": None},
                        "deployment": None,
                        "trigger": Trigger.Automatic,
                        "max-time": None,
                    },
                },
                {
                    "parallel": [
                        {
                            "step": {
                                "name": "Parallel 1",
                                "script": ["cat /etc/os-release"],
                                "image": {
                                    "name": parallel_step_image,
                                    "username": None,
                                    "password": None,
                                    "email": None,
                                    "run-as-user": None,
                                    "aws": None,
                                },
                                "caches": [],
                                "services": ["from_env"],
                                "artifacts": [],
                                "after-script": [],
                                "size": StepSize.Simple,
                                "clone": {"depth": None, "lfs": None, "enabled": None},
                                "deployment": None,
                                "trigger": Trigger.Automatic,
                                "max-time": None,
                            }
                        },
                        {
                            "step": {
                                "name": "Parallel 2",
                                "script": ["cat /etc/os-release"],
                                "image": {
                                    "name": parallel_step_image,
                                    "username": None,
                                    "password": None,
                                    "email": None,
                                    "run-as-user": None,
                                    "aws": None,
                                },
                                "caches": [],
                                "services": ["from_env"],
                                "artifacts": [],
                                "after-script": [],
                                "size": StepSize.Simple,
                                "clone": {"depth": None, "lfs": None, "enabled": None},
                                "deployment": None,
                                "trigger": Trigger.Automatic,
                                "max-time": None,
                            }
                        },
                    ],
                },
            ],
            "branches": [],
            "pull-requests": [],
            "custom": [],
        },
    }

    assert parsed.dict(by_alias=True) == expected
