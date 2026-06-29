import {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget, LongTextWidget,
  ContextWindowWidget,
} from "./widgets";
import RootObjectFieldTemplate from "./RootObjectFieldTemplate";
import DescriptionFieldTemplate from "./DescriptionFieldTemplate";
import VerifyField from "../components/VerifyField";
import ConditionsField from "../components/ConditionsField";

export const customWidgets = {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget, LongTextWidget,
  ContextWindowWidget,
};
export const customFields = { VerifyField, ConditionsField };
export const customTemplates = {
  ObjectFieldTemplate: RootObjectFieldTemplate,
  DescriptionFieldTemplate,
};
