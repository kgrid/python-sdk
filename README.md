## Implementation
### Dependency management
To manage dependencies and make it possible to only install dependencies required for what you want to use from SDK we decided to use Python's Optional Dependencies rather than creating separate packages for each class.

Packaging each class separately has its advantages, especially if each class represents a distinct, independent feature with unique dependencies which is not the case in our usecase. However, using optional dependencies within a single package can offer significant benefits in terms of usability and maintainability. Here’s a comparison to help decide which approach might work best for you

1. Installation Simplicity
With optional dependencies, users install a single package (kgrid) and add only the extra features they need using extras (e.g., kgrid[cli]). This is generally simpler and more user-friendly, as all features are accessible through a single, central package

2. Namespace and Code Organization
Keeping everything in a single package means all classes share the same namespace and project structure, making the API simpler and more cohesive for users. They import from KGrid package regardless of the feature set they need, which simplifies code and documentation.

3. Code Reusability and Dependency Management
A single package with optional dependencies is easier to manage if some classes share common dependencies. You only define common dependencies once, and updates propagate across all features. It also avoids versioning conflicts between interdependent features.

4. User Flexibility and Lightweight Installation
Users can install only what they need, making the package lightweight without requiring multiple packages. It provides flexibility without adding complexity since extras are not installed by default.

5. Version Management and Compatibility
You manage versioning in one central package. Compatibility between the core and extras is generally simpler to control, as everything is versioned and released together.

The current version of SDK only has optional dependencies for Ko_API class. If this class is ised, these optional dependencies could be installed with the package using:
```bash
poetry install -E api
```

or

```bash
pip install kgrid[api] 
```

When adding kgrid as a dependency (to a knowledge object) you can include the api optional dependencies using
```bash
poetry add kgrid -E api
```

## Usage
To inherit the core functionalities of the SDK, extend `kgrid.Ko` in your knowledge object. For example:
```python
from kgrid import Ko

class Prevent_obesity_morbidity_mortality(Ko):
    def __init__(self):
        super().__init__(__package__)
```

Use `kgrid.Ko`_Execution to include the `execute` method in your knowledge object:
```python
from kgrid import Ko_Execution

class Pregnancy_healthy_weight_gain(Ko_Execution):
    def __init__(self):
        super().__init__(__package__, [self.get_pregnancy_healthy_weight_gain_recommendation])
```

In this level, you pass the knowledge function to the constructor of the superclass.

To use the SDK to implement an API or CLI service for your knowledge object, use the `kgrid.Ko_API` and `kgrid.CLI` classes:
```python
from kgrid import Ko_API
from kgrid import Ko_CLI

class Abdominal_aortic_aneurysm_screening(Ko_API,Ko_CLI):
    def __init__(self):
        super().__init__(__package__, [self.get_abdominal_aortic_aneurysm_screening])
```

This will include the `execute` function in your knowledge object as well.

For a complete example of using the SDK to implement API, CLI, and activator services, see the knowledge objects created in our USPSTF collection repository or refer to the code below.
```python
from kgrid import Ko_API
from kgrid import Ko_CLI


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

The activator example requires a service specification file and a deployment file that points to the `apply` method. For more details, please refer to the [Python Activator](https://github.com/kgrid/python-activator) documentation.