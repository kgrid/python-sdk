from abdominal_aortic_aneurysm_screening.abdominal_aortic_aneurysm_screening import abdominal_aortic_aneurysm_screening
from cardiovascular_prevention_diet_activity.cardiovascular_prevention_diet_activity import cardiovascular_prevention_diet_activity
from cardiovascular_prevention_statin_use.cardiovascular_prevention_statin_use import cardiovascular_prevention_statin_use
from hypertension_screening.hypertension_screening import hypertension_screening
from diabetes_screening.diabetes_screening import diabetes_screening
from high_body_mass_index.high_body_mass_index import high_body_mass_index
from kgrid.collection import Collection

def test_collection():
    collection = Collection("USPSTF_Collection_1")
    collection.add_knowledge_object( abdominal_aortic_aneurysm_screening )
    collection.add_knowledge_object( cardiovascular_prevention_diet_activity )
    collection.add_knowledge_object( cardiovascular_prevention_statin_use )
    collection.add_knowledge_object( hypertension_screening )
    collection.add_knowledge_object( diabetes_screening )
    collection.add_knowledge_object( high_body_mass_index )
    
    patient = {
        "age":35,
        "bmi":33,
        "bmi_percentile":95.5,
        "has_never_smoked": True,
        "has_cardiovascular_risk_factors":True,
        "ten_year_CVD_risk":8,
        "hypertension":False        
    }
    result = collection.calculate_for_all(patient)
 
    print(result)
    
    assert 1==1