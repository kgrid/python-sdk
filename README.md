# kgrid_sdk

## Implementation
### Dependency management
To manage dependencies and make it possible to only install dependencies required for what you want to use from SDK we decided to use Python's Optional Dependencies rather than creating separate packages for each class.

Packaging each class separately has its advantages, especially if each class represents a distinct, independent feature with unique dependencies which is not the case in our usecase. However, using optional dependencies within a single package can offer significant benefits in terms of usability and maintainability. Here’s a comparison to help decide which approach might work best for you

1. Installation Simplicity
With optional dependencies, users install a single package (kgrid_sdk) and add only the extra features they need using extras (e.g., kgrid_sdk[cli]). This is generally simpler and more user-friendly, as all features are accessible through a single, central package

2. Namespace and Code Organization
Keeping everything in a single package means all classes share the same namespace and project structure, making the API simpler and more cohesive for users. They import from kgrid_sdk package regardless of the feature set they need, which simplifies code and documentation.

3. Code Reusability and Dependency Management
A single package with optional dependencies is easier to manage if some classes share common dependencies. You only define common dependencies once, and updates propagate across all features. It also avoids versioning conflicts between interdependent features.

4. User Flexibility and Lightweight Installation
Users can install only what they need, making the package lightweight without requiring multiple packages. It provides flexibility without adding complexity since extras are not installed by default.

5. Version Management and Compatibility
You manage versioning in one central package. Compatibility between the core and extras is generally simpler to control, as everything is versioned and released together.

The current version of the SDK only has optional dependencies for Ko_API class. If this class is used, these optional dependencies could be installed with the package using `-E api` if you are using `poetry install` or `poetry add` and using `[api]` if you are using `pip install`.

## Usage
You can use this package to implement python Knowledge Objects.

### use  kgrid_sdk package as a dependency in your Knowledge Object
The `kgrid_sdk` package is available on PyPI and can be easily added as a dependency to your project. Here’s how to include it in your project based on your setup:

#### using Poetry
- For the base package:
```bash
poetry add kgrid_sdk
```

- If you need to use the KO-API class, include the api extra:
```
poetry add kgrid_sdk -E api
```

#### Using pip
If you are not using Poetry, you can install the package with pip:
- For the base package:
```
pip install kgrid_sdk
```
- To include the KO-API extra:
```
pip install kgrid_sdk[api] 
```
### `kgrid_sdk.Ko`
To inherit the core functionalities of the SDK, extend the `kgrid_sdk.Ko` class in your knowledge object. For example:
```python
from kgrid_sdk import Ko

class Prevent_obesity_morbidity_mortality(Ko):
    def __init__(self):
        super().__init__(__package__)
```
This class adds core functionalities to the knowledge object (KO), such as `get_version` and `get_metadata`.

### `kgrid_sdk.Ko_Execution`
The `Ko_Execution` class extends `Ko` to include a universal `execute` method for knowledge objects. The constructor of this class accepts an array of knowledge functions, and the `execute` method can optionally take the name of the function to execute. If no function name is provided, the `execute` method defaults to executing the first function. This is particularly useful for KOs with only one knowledge function.
```python
from kgrid_sdk import Ko_Execution

class Pregnancy_healthy_weight_gain(Ko_Execution):
    def __init__(self):
        super().__init__(__package__, [self.get_pregnancy_healthy_weight_gain_recommendation])

    @staticmethod
    def get_pregnancy_healthy_weight_gain_recommendation(pregnant):
    ...        
```
The `execute` method takes a JSON input, mapping it to the knowledge representation's input parameters using a wrapper. The JSON input may include unrelated parameters, which are ignored by the wrapper.

The `execute` method is used by the SDK's collection class, API, and CLI services.

### `kgrid_sdk.Ko_API` and `kgrid_sdk.CLI`
To implement an API or CLI service for your knowledge object, extend the `kgrid_sdk.Ko_API` and `kgrid_sdk.CLI` classes:
```python
from kgrid_sdk import Ko_API
from kgrid_sdk import Ko_CLI

class Abdominal_aortic_aneurysm_screening(Ko_API,Ko_CLI):
    def __init__(self):
        super().__init__(__package__, [self.get_abdominal_aortic_aneurysm_screening])
```

These classes extend `Ko_Execution` and therefore they include the `execute` method to your knowledge object.

For a complete example of implementing API, CLI, and activator services using the SDK, see the knowledge objects created in our USPSTF collection repository or refer to the example code below:
```python
from kgrid_sdk import Ko_API
from kgrid_sdk import Ko_CLI


class Abdominal_aortic_aneurysm_screening(Ko_API,Ko_CLI):
    def __init__(self):
        super().__init__(__package__, [self.get_abdominal_aortic_aneurysm_screening])
        self.add_endpoint("/check-inclusion", tags=["abdominal_aortic_aneurysm_screening"])
    
    @staticmethod
    def get_abdominal_aortic_aneurysm_screening(age, gender, has_never_smoked):
        """
        Parameters:
        - age (int): Age of the person.
        - gender (int): Gender of the individual (0 for women, 1 for men).    
        - has_never_smoked (bool): Whether this person has never smoked or not.
        """
        
        if gender == 1:
            if age >= 65 and age <= 75 and not has_never_smoked:        
                return {
                    "inclusion": True,
                    "title": "Abdominal Aortic Aneurysm: Screening",
                    "recommendation": "The USPSTF recommends 1-time screening for abdominal aortic aneurysm (AAA) with ultrasonography in men aged 65 to 75 years who have ever smoked.",
                    "grade": "B",
                    "URL": "https://www.uspreventiveservicestaskforce.org/uspstf/index.php/recommendation/abdominal-aortic-aneurysm-screening"
                    }
            elif age >= 65 and age <= 75 and has_never_smoked:  
                return {
                    "inclusion": True,
                    "title": "Abdominal Aortic Aneurysm: Screening",
                    "recommendation": "The USPSTF recommends that clinicians selectively offer screening for AAA with ultrasonography in men aged 65 to 75 years who have never smoked rather than routinely screening all men in this group. Evidence indicates that the net benefit of screening all men in this group is small. In determining whether this service is appropriate in individual cases, patients and clinicians should consider the balance of benefits and harms on the basis of evidence relevant to the patient's medical history, family history, other risk factors, and personal values.",
                    "grade": "C",
                    "URL": "https://www.uspreventiveservicestaskforce.org/uspstf/index.php/recommendation/abdominal-aortic-aneurysm-screening"
                    }
        elif gender == 0:
            if has_never_smoked:        
                return {
                    "inclusion": True,
                    "title": "Abdominal Aortic Aneurysm: Screening",
                    "recommendation": "The USPSTF recommends against routine screening for AAA with ultrasonography in women who have never smoked and have no family history of AAA.",
                    "grade": "D",
                    "URL": "https://www.uspreventiveservicestaskforce.org/uspstf/index.php/recommendation/abdominal-aortic-aneurysm-screening"
                    }
            elif age >= 65 and age <= 75 and not has_never_smoked:  
                return {
                    "inclusion": True,
                    "title": "Abdominal Aortic Aneurysm: Screening",
                    "recommendation": "The USPSTF concludes that the current evidence is insufficient to assess the balance of benefits and harms of screening for AAA with ultrasonography in women aged 65 to 75 years who have ever smoked or have a family history of AAA.",
                    "grade": "I",
                    "URL": "https://www.uspreventiveservicestaskforce.org/uspstf/index.php/recommendation/abdominal-aortic-aneurysm-screening"
                    }

            
        return {
            "inclusion": False,
            "title": "Abdominal Aortic Aneurysm: Screening"    
            }
            

abdominal_aortic_aneurysm_screening = Abdominal_aortic_aneurysm_screening()
app = abdominal_aortic_aneurysm_screening.app

abdominal_aortic_aneurysm_screening.define_cli()
abdominal_aortic_aneurysm_screening.add_argument(
    "-a", "--age", type=float, required=True, help="Age of the person"
)
abdominal_aortic_aneurysm_screening.add_argument(
    "-g", "--gender", type=float, required=True, help="Gender of the individual (0 for women, 1 for men)."
)
abdominal_aortic_aneurysm_screening.add_argument(
    "--has_never_smoked", action='store_true', help="Indicate if the person has never smoked."
)
abdominal_aortic_aneurysm_screening.add_argument(
    "--has_ever_smoked", action='store_false', dest='has_never_smoked', help="Indicate if the person has ever smoked."
)


def cli():
    abdominal_aortic_aneurysm_screening.execute_cli()


def apply(input):
    return abdominal_aortic_aneurysm_screening.execute(input)
```

Note: The activator example requires a service specification file and a deployment file pointing to the `apply` method. For more details, refer to the [Python Activator](https://github.com/kgrid/python-activator) documentation.

### `kgrid_sdk.Collection`
The `kgrid_sdk.Collection` class can be used to create a collection of knowledge objects. Start by importing and creating an instance of the `Collection` class. Use the `add_knowledge_object` method to add knowledge objects that extend `kgrid_sdk.Ko_Execution` or higher-level SDK classes like `kgrid_sdk.Ko_API` or `kgrid_sdk.CLI`. This requirement ensures that the collection works with KOs containing the SDK `execute` method.
```python
from abdominal_aortic_aneurysm_screening import abdominal_aortic_aneurysm_screening
from cardiovascular_prevention_diet_activity import cardiovascular_prevention_diet_activity
from cardiovascular_prevention_statin_use import cardiovascular_prevention_statin_use
from hypertension_screening import hypertension_screening
from diabetes_screening import diabetes_screening
from high_body_mass_index import high_body_mass_index

from kgrid_sdk.collection import Collection


USPSTF_Collection = Collection("USPSTF_Collection")
USPSTF_Collection.add_knowledge_object( abdominal_aortic_aneurysm_screening )
USPSTF_Collection.add_knowledge_object( cardiovascular_prevention_diet_activity )
USPSTF_Collection.add_knowledge_object( cardiovascular_prevention_statin_use )
USPSTF_Collection.add_knowledge_object( hypertension_screening )
USPSTF_Collection.add_knowledge_object( diabetes_screening )
USPSTF_Collection.add_knowledge_object( high_body_mass_index )
```
Once ready, the collection can be packaged and installed as an external package in any Python application. Here is an example:
```bash
pip install https://github.com/kgrid/python-sdk/releases/download/1.0/uspstf_collection-0.1.0-py3-none-any.whl
```

To execute the collection on a patient's data, install and import the `USPSTF_Collection` (if used as a package). Use the `calculate_for_all` method, passing a JSON input that includes all the required parameters for each knowledge object in the collection.
```python
from uspstf_collection import USPSTF_Collection
import json

patient_data={
    "age":42,
    "bmi":33,
    "bmi_percentile":95.5,
    "has_never_smoked": True,
    "has_cardiovascular_risk_factors":True,
    "ten_year_CVD_risk":8,
    "hypertension":False        
}

result = USPSTF_Collection.calculate_for_all(patient_data)
print(json.dumps(result, indent=4))
```