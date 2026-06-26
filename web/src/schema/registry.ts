import {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget, LongTextWidget,
} from "./widgets";
import RootObjectFieldTemplate from "./RootObjectFieldTemplate";
import DescriptionFieldTemplate from "./DescriptionFieldTemplate";
import VerifyField from "../components/VerifyField";

export const customWidgets = {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget, LongTextWidget,
};
export const customFields = { VerifyField };
export const customTemplates = {
  ObjectFieldTemplate: RootObjectFieldTemplate,
  DescriptionFieldTemplate,
};
