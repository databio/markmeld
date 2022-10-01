<script>
document.addEventListener('DOMContentLoaded', (event) => {
  document.querySelectorAll('h3 code').forEach((block) => {
    hljs.highlightBlock(block);
  });
});
</script>

<style>
h3 .content { 
    padding-left: 22px;
    text-indent: -15px;
 }
h3 .hljs .content {
    padding-left: 20px;
    margin-left: 0px;
    text-indent: -15px;
    martin-bottom: 0px;
}
h4 .content, table .content, p .content, li .content { margin-left: 30px; }
h4 .content { 
    font-style: italic;
    font-size: 1em;
    margin-bottom: 0px;
}

</style>


# Package `looper` Documentation

## <a name="Project"></a> Class `Project`
Looper-specific Project.

#### Parameters:

- `config_file` (`str`):  path to configuration file with data fromwhich Project is to be built
- `amendments` (`Iterable[str]`):  name indicating amendment to use, optional
- `divcfg_path` (`str`):  path to an environment configuration YAML filespecifying compute settings.
- `permissive` (`bool`):  Whether a error should be thrown ifa sample input file(s) do not exist or cannot be open.
- `compute_env_file` (`str`):  Environment configuration YAML file specifyingcompute settings.


```python
def __init__(self, config_file, amendments=None, divcfg_path=None, runp=False, **kwargs)
```

Initialize self.  See help(type(self)) for accurate signature.



```python
def amendments(self)
```

Return currently active list of amendments or None if none was activated
#### Returns:

- `Iterable[str]`:  a list of currently active amendment names




```python
def build_submission_bundles(self, protocol, priority=True)
```

Create pipelines to submit for each sample of a particular protocol.

With the argument (flag) to the priority parameter, there's control
over whether to submit pipeline(s) from only one of the project's
known pipeline locations with a match for the protocol, or whether to
submit pipelines created from all locations with a match for the
protocol.
#### Parameters:

- `protocol` (`str`):  name of the protocol/library for which tocreate pipeline(s)
- `priority` (`bool`):  to only submit pipeline(s) from the first of thepipelines location(s) (indicated in the project config file) that has a match for the given protocol; optional, default True


#### Returns:

- `Iterable[(PipelineInterface, type, str, str)]`: 


#### Raises:

- `AssertionError`:  if there's a failure in the attempt topartition an interface's pipeline scripts into disjoint subsets of those already mapped and those not yet mapped




```python
def cli_pifaces(self)
```

Collection of pipeline interface sources specified in object constructor
#### Returns:

- `list[str]`:  collection of pipeline interface sources




```python
def config(self)
```

Get the config mapping
#### Returns:

- `Mapping`:  config. May be formatted to comply with the mostrecent version specifications




```python
def config_file(self)
```

Get the config file path
#### Returns:

- `str`:  path to the config file




```python
def get_sample_piface(self, sample_name)
```

Get a list of pipeline interfaces associated with the specified sample.

Note that only valid pipeline interfaces will show up in the
result (ones that exist on disk/remotely and validate successfully
against the schema)
#### Parameters:

- `sample_name` (`str`):  name of the sample to retrieve list ofpipeline interfaces for


#### Returns:

- `list[looper.PipelineInterface]`:  collection of validpipeline interfaces associated with selected sample




```python
def get_schemas(pifaces, schema_key='input_schema')
```

Get the list of unique schema paths for a list of pipeline interfaces
#### Parameters:

- `pifaces` (`str | Iterable[str]`):  pipeline interfaces to searchschemas for
- `schema_key` (`str`):  where to look for schemas in the piface


#### Returns:

- `Iterable[str]`:  unique list of schema file paths




```python
def list_amendments(self)
```

Return a list of available amendments or None if not declared
#### Returns:

- `Iterable[str]`:  a list of available amendment names




```python
def make_project_dirs(self)
```

Create project directory structure if it doesn't exist.



```python
def output_dir(self)
```

Output directory for the project, specified in object constructor
#### Returns:

- `str`:  path to the output directory




```python
def piface_key(self)
```

Name of the pipeline interface attribute for this project
#### Returns:

- `str`:  name of the pipeline interface attribute




```python
def pipeline_interface_sources(self)
```

Get a list of all valid pipeline interface sources associated with this project. Sources that are file paths are expanded
#### Returns:

- `list[str]`:  collection of valid pipeline interface sources




```python
def pipeline_interfaces(self)
```

Flat list of all valid interface objects associated with this Project

Note that only valid pipeline interfaces will show up in the
result (ones that exist on disk/remotely and validate successfully
against the schema)
#### Returns:

- `list[looper.PipelineInterface]`:  list of pipeline interfaces




```python
def populate_pipeline_outputs(self, check_exist=False)
```

Populate project and sample output attributes based on output schemas that pipeline interfaces point to. Additionally, if requested,  check for the constructed paths existence on disk



```python
def project_pipeline_interface_sources(self)
```

Get a list of all valid project-level pipeline interface sources associated with this project. Sources that are file paths are expanded
#### Returns:

- `list[str]`: 




```python
def project_pipeline_interfaces(self)
```

Flat list of all valid project-level interface objects associated with this Project

Note that only valid pipeline interfaces will show up in the
result (ones that exist on disk/remotely and validate successfully
against the schema)
#### Returns:

- `list[looper.PipelineInterface]`:  list of pipeline interfaces




```python
def results_folder(self)
```

Path to the results folder for the project
#### Returns:

- `str`:  path to the results folder in the output folder




```python
def sample_name_colname(self)
```

Name of the effective sample name containing column in the sample table.

It is "sample_name" bu default, but when it's missing it could be
replaced by the selected sample table index, defined on the
object instantiation stage.
#### Returns:

- `str`:  name of the column that consist of sample identifiers




```python
def sample_table(self)
```

Get sample table. If any sample edits were performed, it will be re-generated
#### Returns:

- `pandas.DataFrame`:  a data frame with current samples attributes




```python
def samples(self)
```

Generic/base Sample instance for each of this Project's samples.
#### Returns:

- `Iterable[Sample]`:  Sample instance for eachof this Project's samples




```python
def selected_compute_package(self)
```

Compute package name specified in object constructor
#### Returns:

- `str`:  compute package name




```python
def submission_folder(self)
```

Path to the submission folder for the project
#### Returns:

- `str`:  path to the submission in the output folder




```python
def subsample_table(self)
```

Get subsample table
#### Returns:

- `pandas.DataFrame`:  a data frame with subsample attributes




```python
def toggle_key(self)
```

Name of the toggle attribute for this project
#### Returns:

- `str`:  name of the toggle attribute




## <a name="PipelineInterface"></a> Class `PipelineInterface`
This class parses, holds, and returns information for a yaml file that specifies how to interact with each individual pipeline. This includes both resources to request for cluster job submission, as well as arguments to be passed from the sample annotation metadata to the pipeline

#### Parameters:

- `config` (`str | Mapping`):  path to file from which to parseconfiguration data, or pre-parsed configuration data.
- `pipeline_type` (`str`):  type of the pipeline,must be either 'sample' or 'project'.


```python
def __init__(self, config, pipeline_type=None)
```

Initialize self.  See help(type(self)) for accurate signature.



```python
def choose_resource_package(self, namespaces, file_size)
```

Select resource bundle for given input file size to given pipeline.
#### Parameters:

- `file_size` (`float`):  Size of input data (in gigabytes).
- `namespaces` (`Mapping[Mapping[str]]`):  namespaced variables to passas a context for fluid attributes command rendering


#### Returns:

- `MutableMapping`:  resource bundle appropriate for given pipeline,for given input file size


#### Raises:

- `ValueError`:  if indicated file size is negative, or if thefile size value specified for any resource package is negative
- `InvalidResourceSpecificationException`:  if no defaultresource package specification is provided




```python
def copy(self)
```

Copy self to a new object.



```python
def get_pipeline_schemas(self, schema_key='input_schema')
```

Get path to the pipeline schema.
#### Parameters:

- `schema_key` (`str`):  where to look for schemas in the pipeline iface


#### Returns:

- `str`:  absolute path to the pipeline schema file




## <a name="SubmissionConductor"></a> Class `SubmissionConductor`
Collects and then submits pipeline jobs.

This class holds a 'pool' of commands to submit as a single cluster job.
Eager to submit a job, each instance's collection of commands expands until
it reaches the 'pool' has been filled, and it's therefore time to submit the
job. The pool fills as soon as a fill criteria has been reached, which can
be either total input file size or the number of individual commands.


```python
def __init__(self, pipeline_interface, prj, delay=0, extra_args=None, extra_args_override=None, ignore_flags=False, compute_variables=None, max_cmds=None, max_size=None, automatic=True, collate=False)
```

Create a job submission manager.

The most critical inputs are the pipeline interface and the pipeline
key, which together determine which provide critical pipeline
information like resource allocation packages and which pipeline will
be overseen by this instance, respectively.
#### Parameters:

- `pipeline_interface` (`PipelineInterface`):  Collection of importantdata for one or more pipelines, like resource allocation packages and option/argument specifications
- `prj` (``):  Project with which each sample being considered isassociated (what generated each sample)
- `delay` (`float`):  Time (in seconds) to wait before submitting a jobonce it's ready
- `extra_args` (`str`):  string to pass to each job generated,for example additional pipeline arguments
- `extra_args_override` (`str`):  string to pass to each job generated,for example additional pipeline arguments. This deactivates the 'extra' functionality that appends strings defined in Sample.command_extra and Project.looper.command_extra to the command template.
- `ignore_flags` (`bool`):  Whether to ignore flag files present inthe sample folder for each sample considered for submission
- `compute_variables` (`dict[str]`):  A dict with variables that will be madeavailable to the compute package. For example, this should include the name of the cluster partition to which job or jobs will be submitted
- `max_cmds` (`int | NoneType`):  Upper bound on number of commands toinclude in a single job script.
- `max_size` (`int | float | NoneType`):  Upper bound on total filesize of inputs used by the commands lumped into single job script.
- `automatic` (`bool`):  Whether the submission should be automatic oncethe pool reaches capacity.
- `collate` (`bool`):  Whether a collate job is to be submitted (runs onthe project level, rather that on the sample level)




```python
def add_sample(self, sample, rerun=False)
```

Add a sample for submission to this conductor.
#### Parameters:

- `sample` (`peppy.Sample`):  sample to be included with this conductor'scurrently growing collection of command submissions
- `rerun` (`bool`):  whether the given sample is being rerun rather thanrun for the first time


#### Returns:

- `bool`:  Indication of whether the given sample was added tothe current 'pool.'


#### Raises:

- `TypeError`:  If sample subtype is provided but does not extendthe base Sample class, raise a TypeError.




```python
def failed_samples(self)
```



```python
def num_cmd_submissions(self)
```

Return the number of commands that this conductor has submitted.
#### Returns:

- `int`:  Number of commands submitted so far.




```python
def num_job_submissions(self)
```

Return the number of jobs that this conductor has submitted.
#### Returns:

- `int`:  Number of jobs submitted so far.




```python
def submit(self, force=False)
```

Submit one or more commands as a job.

This call will submit the commands corresponding to the current pool 
of samples if and only if the argument to 'force' evaluates to a 
true value, or the pool of samples is full.
#### Parameters:

- `force` (`bool`):  Whether submission should be done/simulated evenif this conductor's pool isn't full.


#### Returns:

- `bool`:  Whether a job was submitted (or would've been ifnot for dry run)




```python
def write_script(self, pool, size)
```

Create the script for job submission.
#### Parameters:

- `pool` (`Iterable[peppy.Sample]`):  collection of sample instances
- `size` (`float`):  cumulative size of the given pool


#### Returns:

- `str`:  Path to the job submission script created.




```python
def write_skipped_sample_scripts(self)
```

For any sample skipped during initial processing write submission script






*Version Information: `looper` v1.2.1, generated by `lucidoc` v0.4.2*